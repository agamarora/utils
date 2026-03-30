use luna_common::types::RateLimitEntry;
use std::fs;
use std::io::Write;
use std::path::Path;

/// Append a rate limit entry to the JSONL file. Fire-and-forget.
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

/// Truncate JSONL file to last `max_entries` lines on startup.
pub fn rotate(path: &Path, max_entries: usize) {
    let _ = (|| -> std::io::Result<()> {
        let content = fs::read_to_string(path)?;
        let lines: Vec<&str> = content.lines().collect();
        if lines.len() > max_entries {
            let kept = &lines[lines.len() - max_entries..];
            let mut file = fs::File::create(path)?;
            for line in kept {
                writeln!(file, "{}", line)?;
            }
        }
        Ok(())
    })();
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn make_entry(util: f64) -> RateLimitEntry {
        RateLimitEntry {
            five_h_utilization: Some(util),
            seven_d_utilization: None,
            five_h_reset: None,
            seven_d_reset: None,
            status: None,
            ts: "2026-03-30T12:00:00Z".to_string(),
        }
    }

    #[test]
    fn test_write_and_append() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("test.jsonl");
        write_entry(&path, &make_entry(0.1));
        write_entry(&path, &make_entry(0.2));
        let content = fs::read_to_string(&path).unwrap();
        assert_eq!(content.lines().count(), 2);
        assert!(content.contains("0.1"));
        assert!(content.contains("0.2"));
    }

    #[test]
    fn test_rotate_over_limit() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("test.jsonl");
        for i in 0..15 {
            write_entry(&path, &make_entry(i as f64 / 100.0));
        }
        rotate(&path, 10);
        let content = fs::read_to_string(&path).unwrap();
        assert_eq!(content.lines().count(), 10);
        assert!(content.contains("0.05"));
        assert!(!content.contains("0.04"));
    }

    #[test]
    fn test_rotate_missing_file() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("nonexistent.jsonl");
        rotate(&path, 10); // should not panic
    }
}
