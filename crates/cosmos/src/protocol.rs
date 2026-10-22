use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

pub const MAJOR: u32 = 1;
pub const MAX_MESSAGE: usize = 1024 * 1024;

#[derive(Debug, Deserialize, Serialize)]
pub struct Request {
    pub jsonrpc: String,
    pub id: Value,
    pub method: String,
    #[serde(default = "empty_params")]
    pub params: Value,
}
fn empty_params() -> Value {
    json!({})
}
pub fn success(id: Value, result: Value) -> Value {
    json!({"jsonrpc":"2.0", "id":id,"result":result})
}
pub fn failure(id: Value, code: i32, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}
// Newline-delimited JSON with a hard allocation bound, including unterminated messages.
pub fn read_frame(reader: &mut impl BufRead) -> io::Result<Option<Vec<u8>>> {
    let mut data = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return if data.is_empty() {
                Ok(None)
            } else {
                Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "unterminated frame",
                ))
            };
        }
        let end = available.iter().position(|b| *b == b'\n');
        let count = end.map_or(available.len(), |n| n + 1);
        if data.len() + count > MAX_MESSAGE {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "message too large",
            ));
        }
        data.extend_from_slice(&available[..count]);
        reader.consume(count);
        if end.is_some() {
            return Ok(Some(data));
        }
    }
}
pub fn write_frame(writer: &mut impl Write, value: &Value) -> io::Result<()> {
    let body = serde_json::to_vec(value)?;
    if body.len() + 1 > MAX_MESSAGE {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "response too large",
        ));
    }
    writer.write_all(&body)?;
    writer.write_all(b"\n")?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn frames_have_bounded_size_and_require_delimiters() {
        assert!(read_frame(&mut &b"partial"[..]).is_err());
        assert!(read_frame(&mut vec![b'x'; MAX_MESSAGE + 1].as_slice()).is_err());
        let mut input = &b"{}\n[]\n"[..];
        assert_eq!(read_frame(&mut input).unwrap().unwrap(), b"{}\n");
        assert_eq!(read_frame(&mut input).unwrap().unwrap(), b"[]\n");
        assert!(read_frame(&mut input).unwrap().is_none());
    }
}
