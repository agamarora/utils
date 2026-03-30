mod app;
mod config;
mod growth;
mod paths;
mod types;
mod proxy;
mod proxy_lifecycle;
mod collectors;
mod panels;
mod ui;

use clap::Parser;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "luna-tt", version, about = "A living visual credential for AI builders")]
struct Cli {
    /// Export growth state to a file
    #[arg(long, value_name = "FILE")]
    export: Option<PathBuf>,

    /// Import growth state from a file
    #[arg(long, value_name = "FILE")]
    import: Option<PathBuf>,

    /// Reset growth state (clear all progress)
    #[arg(long)]
    reset: bool,

    /// Run in proxy-only mode (no TUI)
    #[arg(long, hide = true)]
    proxy_mode: bool,
}

fn main() {
    let cli = Cli::parse();

    // Handle export
    if let Some(path) = &cli.export {
        match growth::export_state(path) {
            Ok(info) => {
                println!("Exported growth state to {}", path.display());
                println!("  Age: {} days", info.age_days);
                println!("  Particles: {}", info.total_particles);
                println!("  Created: {}", info.created_at);
            }
            Err(e) => {
                eprintln!("Export failed: {}", e);
                std::process::exit(1);
            }
        }
        return;
    }

    // Handle import
    if let Some(path) = &cli.import {
        println!("This will replace your current growth. Continue? [y/N]");
        let mut input = String::new();
        std::io::stdin().read_line(&mut input).ok();
        if input.trim().to_lowercase() != "y" {
            println!("Cancelled.");
            return;
        }
        match growth::import_state(path) {
            Ok(info) => {
                println!("Imported growth state from {}", path.display());
                println!("  Particles: {}", info.total_particles);
            }
            Err(e) => {
                eprintln!("Import failed: {}", e);
                std::process::exit(1);
            }
        }
        return;
    }

    // Handle reset
    if cli.reset {
        println!("This will permanently delete your growth. Continue? [y/N]");
        let mut input = String::new();
        std::io::stdin().read_line(&mut input).ok();
        if input.trim().to_lowercase() != "y" {
            println!("Cancelled.");
            return;
        }
        if let Some(path) = paths::growth_state_file() {
            let _ = std::fs::remove_file(&path);
            println!("Growth state cleared.");
        }
        return;
    }

    // Handle proxy-only mode
    if cli.proxy_mode {
        let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
        rt.block_on(async {
            let config = config::Config::load();
            proxy::server::run(config.proxy_port).await;
        });
        return;
    }

    // Normal mode: run the TUI
    if let Err(e) = app::run() {
        eprintln!("luna-tt error: {}", e);
        std::process::exit(1);
    }
}
