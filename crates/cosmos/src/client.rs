//! Compatibility checks happen before acquiring terminal state.
use serde_json::Value;
pub const PANEL_CAPABILITIES: &[&str] =
    &["settings", "actions", "events", "ui-model", "notifications"];
pub fn require_panel(info: &Value) -> Result<(), String> {
    let major = info["protocol_major"].as_u64().unwrap_or(0);
    let minor = info["protocol_minor"].as_u64().unwrap_or(0);
    let capabilities = info["capabilities"].as_array();
    let missing: Vec<_> = PANEL_CAPABILITIES
        .iter()
        .filter(|c| !capabilities.is_some_and(|a| a.iter().any(|v| v.as_str() == Some(**c))))
        .copied()
        .collect();
    if major != u64::from(crate::protocol::MAJOR) || minor < 1 || !missing.is_empty() {
        return Err(format!("running coordinator uses protocol {major}.{minor}; panel requires 1.1 and capabilities [{}]. Restart/upgrade the coordinator; replacing the executable alone does not upgrade a running service. Terminal sessions need not be stopped.",missing.join(", ")));
    }
    Ok(())
}
pub fn panel_preflight() -> Result<Value, String> {
    let info = crate::server::rpc(
        "initialize",
        serde_json::json!({"protocol_major":crate::protocol::MAJOR}),
    )?;
    require_panel(&info)?;
    Ok(info)
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn an_alive_old_coordinator_is_not_panel_compatible() {
        let old = json!({"protocol_major":1,"protocol_minor":0,"capabilities":["settings","notification-state","mod-lifecycle"]});
        let error = require_panel(&old).unwrap_err();
        assert!(error.contains("protocol 1.0"));
        let current =
            json!({"protocol_major":1,"protocol_minor":1,"capabilities":PANEL_CAPABILITIES});
        assert!(require_panel(&current).is_ok());
        let mut missing = current;
        missing["capabilities"] = json!([]);
        assert!(require_panel(&missing).is_err());
    }
}
