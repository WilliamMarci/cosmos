use cosmos::config::Config;
use serde_json::json;

#[test]
fn reader_and_ui_mod_defaults_preserve_old_configuration() {
    let config: Config = serde_json::from_value(json!({"version":1,"theme":"dark"})).unwrap();
    config.validate().unwrap();
    assert_eq!(config.viewer_disk_cache_mb, 512);
    assert_eq!(config.viewer_pdf_edge, 2400);
    assert_eq!(config.viewer_pdf_page_mb, 32);
    assert!(config.ui_mods.is_empty());
}

#[test]
fn reader_limits_and_mod_notification_policies_are_validated() {
    let mut value = serde_json::to_value(Config::default()).unwrap();
    value["ui_mod_paths"] = json!(["/tmp/movable-calendar"]);
    value["ui_mods"] = json!({"calendar":{"enabled":false,"notifications":true}});
    let config: Config = serde_json::from_value(value.clone()).unwrap();
    config.validate().unwrap();
    value["viewer_disk_cache_mb"] = json!(8193);
    assert!(serde_json::from_value::<Config>(value.clone())
        .unwrap()
        .validate()
        .is_err());
    value["viewer_disk_cache_mb"] = json!(512);
    value["ui_mods"]["calendar"]["filesystem"] = json!(true);
    assert!(serde_json::from_value::<Config>(value)
        .unwrap()
        .validate()
        .is_err());
}
