pub mod bridge;
pub mod export;
pub mod workspace;

#[cfg(test)]
mod launch_focus {
    /// The window is built on Ready, after macOS has already activated the app.
    /// Creation orders it front and does not activate, so the first launch
    /// sometimes stays behind. The launch main must focus it, once.
    #[test]
    fn launch_window_takes_foreground_focus() {
        let src = include_str!("main.rs");
        let launch = src
            .split_once("#[cfg(not(test))]\nfn main()")
            .map(|(_, rest)| rest)
            .unwrap_or("");
        assert!(
            launch.contains("focus_on_launch"),
            "the pupil window is created on launch without taking foreground focus"
        );
        assert!(
            src.contains(".set_focus()"),
            "focus_on_launch does not ask the window for foreground focus"
        );
    }
}
