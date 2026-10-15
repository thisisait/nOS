//! The person's CSV export: one new file in the folder given, never over one that is there.
use nos_pupil::export::save_csv;
use std::os::unix::fs::PermissionsExt;

fn dir(name: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("pupil-export-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn a_csv_is_a_new_0600_file_and_a_second_never_overwrites_the_first() {
    let d = dir("new");
    let a = save_csv(&d, "Faktury", "a\r\n1\r\n").unwrap();
    let b = save_csv(&d, "Faktury", "a\r\n2\r\n").unwrap();
    assert_eq!(a, d.join("Faktury.csv"));
    assert_eq!(b, d.join("Faktury-2.csv"));
    assert_eq!(std::fs::read_to_string(&a).unwrap(), "a\r\n1\r\n", "the first is untouched");
    assert_eq!(std::fs::metadata(&b).unwrap().permissions().mode() & 0o777, 0o600);
}

#[test]
fn a_name_that_could_be_a_path_or_a_text_over_the_cap_is_refused() {
    let d = dir("bad");
    for name in ["../x", "a/b", "", ".hidden", &"x".repeat(65)] {
        assert!(save_csv(&d, name, "a").is_err(), "{name:?} was accepted");
    }
    assert!(save_csv(&d, "big", &"x".repeat(4 * 1024 * 1024 + 1)).is_err(), "over 4 MiB was accepted");
    assert_eq!(std::fs::read_dir(&d).unwrap().count(), 0, "a refusal writes nothing");
}
