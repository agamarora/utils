/// SSE event accumulator: extracts model, usage, and stop_reason from a
/// Server-Sent Events stream without modifying the stream itself.
pub struct SseAccumulator {
    current_event: String,
    model: Option<String>,
    input_tokens: Option<u64>,
    output_tokens: Option<u64>,
    cache_read_tokens: Option<u64>,
    stop_reason: Option<String>,
}

impl SseAccumulator {
    pub fn new() -> Self {
        Self {
            current_event: String::new(),
            model: None,
            input_tokens: None,
            output_tokens: None,
            cache_read_tokens: None,
            stop_reason: None,
        }
    }

    /// Feed a single SSE line (without trailing newline).
    pub fn feed_line(&mut self, line: &str) {
        if let Some(event_type) = line.strip_prefix("event: ") {
            self.current_event = event_type.trim().to_string();
        } else if let Some(data) = line.strip_prefix("data: ") {
            self.parse_data(data.trim());
        }
        // Ignore other lines (comments, id:, retry:, blank)
    }

    fn parse_data(&mut self, data: &str) {
        let json: serde_json::Value = match serde_json::from_str(data) {
            Ok(v) => v,
            Err(_) => return,
        };

        match self.current_event.as_str() {
            "message_start" => {
                // { "type": "message_start", "message": { "model": "...", "usage": { "input_tokens": N, "cache_read_input_tokens": N } } }
                if let Some(msg) = json.get("message") {
                    if let Some(model) = msg.get("model").and_then(|v| v.as_str()) {
                        self.model = Some(model.to_string());
                    }
                    if let Some(usage) = msg.get("usage") {
                        if let Some(input) = usage.get("input_tokens").and_then(|v| v.as_u64()) {
                            self.input_tokens = Some(input);
                        }
                        if let Some(cache) = usage.get("cache_read_input_tokens").and_then(|v| v.as_u64()) {
                            self.cache_read_tokens = Some(cache);
                        }
                    }
                }
            }
            "message_delta" => {
                // { "type": "message_delta", "delta": { "stop_reason": "..." }, "usage": { "output_tokens": N } }
                if let Some(delta) = json.get("delta") {
                    if let Some(reason) = delta.get("stop_reason").and_then(|v| v.as_str()) {
                        self.stop_reason = Some(reason.to_string());
                    }
                }
                if let Some(usage) = json.get("usage") {
                    if let Some(output) = usage.get("output_tokens").and_then(|v| v.as_u64()) {
                        self.output_tokens = Some(output);
                    }
                }
            }
            _ => {
                // For any other event type, check for usage fields generically
                if let Some(usage) = json.get("usage") {
                    if self.input_tokens.is_none() {
                        if let Some(input) = usage.get("input_tokens").and_then(|v| v.as_u64()) {
                            self.input_tokens = Some(input);
                        }
                    }
                    if let Some(cache) = usage.get("cache_read_input_tokens").and_then(|v| v.as_u64()) {
                        self.cache_read_tokens = Some(cache);
                    }
                }
            }
        }
    }

    /// Finish accumulation and return extracted fields.
    pub fn finish(self) -> (Option<String>, Option<u64>, Option<u64>, Option<u64>, Option<String>) {
        (
            self.model,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.stop_reason,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_message_start() {
        let mut acc = SseAccumulator::new();
        acc.feed_line("event: message_start");
        acc.feed_line(r#"data: {"type":"message_start","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":3847,"cache_read_input_tokens":2100}}}"#);
        let (model, input, _, cache, _) = acc.finish();
        assert_eq!(model.as_deref(), Some("claude-sonnet-4-6"));
        assert_eq!(input, Some(3847));
        assert_eq!(cache, Some(2100));
    }

    #[test]
    fn test_parse_message_delta() {
        let mut acc = SseAccumulator::new();
        acc.feed_line("event: message_delta");
        acc.feed_line(r#"data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":1205}}"#);
        let (_, _, output, _, stop) = acc.finish();
        assert_eq!(output, Some(1205));
        assert_eq!(stop.as_deref(), Some("tool_use"));
    }

    #[test]
    fn test_full_stream() {
        let mut acc = SseAccumulator::new();
        acc.feed_line("event: message_start");
        acc.feed_line(r#"data: {"type":"message_start","message":{"model":"claude-opus-4-6","usage":{"input_tokens":5000,"cache_read_input_tokens":3000}}}"#);
        acc.feed_line("");
        acc.feed_line("event: content_block_start");
        acc.feed_line(r#"data: {"type":"content_block_start","index":0}"#);
        acc.feed_line("");
        acc.feed_line("event: message_delta");
        acc.feed_line(r#"data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":800}}"#);

        let (model, input, output, cache, stop) = acc.finish();
        assert_eq!(model.as_deref(), Some("claude-opus-4-6"));
        assert_eq!(input, Some(5000));
        assert_eq!(output, Some(800));
        assert_eq!(cache, Some(3000));
        assert_eq!(stop.as_deref(), Some("end_turn"));
    }
}
