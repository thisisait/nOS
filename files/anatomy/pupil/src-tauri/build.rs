fn main() {
    #[cfg(feature = "app")]
    tauri_build::build()
}
