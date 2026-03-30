use crate::types::RateLimitEntry;
use std::fs;
use std::io::Write;
use std::path::Path;

/// Append a rate limit entry as a JSON line. Fire-and-forget.
pub fn write_entry(path: &Path, entry: &RateLimitEntry) {
    let _ = (|| -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let line = serde_json::to_string(entry).map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::Other, e)
        })?;
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;
        writeln!(file, "{}", line)?;
        Ok(())
    })();
}

/// Truncate JSONL file to last `max_lines` lines.
pub fn rotate(path: &Path, max_lines: usize) {
    let _ = (|| -> std::io::Result<()> {
        let content = fs::read_to_string(path)?;
        let lines: Vec<&str> = content.lines().collect();
        if lines.len() > max_lines {
            let kept = &lines[lines.len() - max_lines..];
            let mut file = fs::File::create(path)?;
            for line in kept {
                writeln!(file, "{}", line)?;
            }
        }
        Ok(())
    })();
}
