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

#[test]
fn rich_reader_defaults_and_ranges_are_validated() {
    let config = Config::default();
    assert_eq!(config.viewer_rich_columns, "auto");
    assert_eq!(config.viewer_rich_mode, "pages");
    assert_eq!(config.viewer_inline_image_rows, 8);
    assert_eq!(config.viewer_icon_max_px, 64);
    let base = serde_json::to_value(config).unwrap();
    for (key, value) in [
        ("viewer_rich_columns", json!("4")),
        ("viewer_rich_mode", json!("invalid")),
        ("viewer_inline_image_rows", json!(0)),
        ("viewer_icon_max_px", json!(257)),
    ] {
        let mut invalid = base.clone();
        invalid[key] = value;
        assert!(
            serde_json::from_value::<Config>(invalid)
                .unwrap()
                .validate()
                .is_err(),
            "{key}"
        );
    }
    let mut valid = base;
    valid["viewer_rich_columns"] = json!("2");
    valid["viewer_rich_mode"] = json!("scroll");
    valid["viewer_inline_image_rows"] = json!(18);
    valid["viewer_icon_max_px"] = json!(0);
    let value: Config = serde_json::from_value(valid.clone()).unwrap();
    value.validate().unwrap();
    assert_eq!(serde_json::to_value(value).unwrap(), valid);
}
