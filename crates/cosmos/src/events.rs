use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    sync::{Condvar, Mutex},
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Serialize)]
pub struct Event {
    pub seq: u64,
    pub topic: String,
    pub data: Value,
}
struct Inner {
    next: u64,
    queue: VecDeque<Event>,
}
pub struct Bus {
    epoch: String,
    capacity: usize,
    inner: Mutex<Inner>,
    changed: Condvar,
}
impl Bus {
    pub fn new(epoch: String, capacity: usize) -> Self {
        Self {
            epoch,
            capacity: capacity.max(1),
            inner: Mutex::new(Inner {
                next: 1,
                queue: VecDeque::new(),
            }),
            changed: Condvar::new(),
        }
    }
    pub fn publish(&self, topic: &str, data: Value) -> u64 {
        let mut inner = self.inner.lock().unwrap();
        let seq = inner.next;
        inner.next += 1;
        inner.queue.push_back(Event {
            seq,
            topic: topic.into(),
            data,
        });
        while inner.queue.len() > self.capacity {
            inner.queue.pop_front();
        }
        self.changed.notify_all();
        seq
    }
    pub fn cursor(&self) -> u64 {
        self.inner.lock().unwrap().next - 1
    }
    pub fn poll(&self, p: &Value) -> Result<Value, String> {
        let after = p["after"]
            .as_u64()
            .ok_or("after must be an unsigned cursor")?;
        let limit = p["limit"].as_u64().unwrap_or(100).clamp(1, 256) as usize;
        let wait = p["wait_ms"].as_u64().unwrap_or(0).min(2000);
        let topics: Vec<&str> = p["topics"]
            .as_array()
            .map(|a| a.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        let deadline = Instant::now() + Duration::from_millis(wait);
        let mut inner = self.inner.lock().unwrap();
        loop {
            let first = inner.queue.front().map(|e| e.seq).unwrap_or(inner.next);
            let gap = after.saturating_add(1) < first
                || after >= inner.next
                || p["epoch"].as_str().is_some_and(|s| s != self.epoch);
            if gap {
                return Ok(
                    json!({"epoch":self.epoch,"gap":true,"events":[],"cursor":inner.next-1,"resync":"state.snapshot"}),
                );
            }
            let selected: Vec<_> = inner
                .queue
                .iter()
                .filter(|e| {
                    e.seq > after && (topics.is_empty() || topics.contains(&e.topic.as_str()))
                })
                .take(limit)
                .cloned()
                .collect();
            if !selected.is_empty() || Instant::now() >= deadline {
                // If filtering exhausted the queue, advance past irrelevant events.
                let cursor = if selected.len() == limit {
                    selected.last().unwrap().seq
                } else {
                    inner.next - 1
                };
                return Ok(
                    json!({"epoch":self.epoch,"gap":false,"events":selected,"cursor":cursor}),
                );
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            inner = self.changed.wait_timeout(inner, remaining).unwrap().0;
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn replay_detects_gaps_and_epoch_changes() {
        let bus = Bus::new("one".into(), 2);
        bus.publish("x", json!(1));
        bus.publish("y", json!(2));
        bus.publish("x", json!(3));
        assert_eq!(bus.poll(&json!({"after":0})).unwrap()["gap"], true);
        let reply = bus.poll(&json!({"after":1,"topics":["x"]})).unwrap();
        assert_eq!(reply["events"][0]["seq"], 3);
        assert_eq!(reply["cursor"], 3);
        assert_eq!(
            bus.poll(&json!({"after":3,"epoch":"old"})).unwrap()["gap"],
            true
        );
    }
    #[test]
    fn long_poll_wakes_on_publish() {
        let bus = std::sync::Arc::new(Bus::new("one".into(), 10));
        let writer = bus.clone();
        let task = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(20));
            writer.publish("ready", json!({}));
        });
        let reply = bus.poll(&json!({"after":0,"wait_ms":500})).unwrap();
        task.join().unwrap();
        assert_eq!(reply["events"][0]["topic"], "ready");
    }
}
