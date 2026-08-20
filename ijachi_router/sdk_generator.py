"""Multi-Language Client SDK Generator for ijachi-llm-router.

Generates native client SDKs for TypeScript / Node.js, Go, and Rust.
"""

from __future__ import annotations

from pathlib import Path


class SDKGenerator:
    """Generates multi-language native client SDKs."""

    TYPESCRIPT_SDK = """/**
 * ijachi-llm-router Native TypeScript / Node.js SDK
 */
export interface RouteOptions {
  prompt: str;
  priority?: 'cost' | 'speed' | 'quality' | 'balanced';
  maxCost?: number;
  baseUrl?: str;
}

export interface RouteResponse {
  text: string;
  model: string;
  provider: string;
  costUsd: number;
  latencySec: number;
}

export async function route(options: RouteOptions): Promise<RouteResponse> {
  const baseUrl = options.baseUrl || 'http://127.0.0.1:8000';
  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: options.priority || 'quality',
      messages: [{ role: 'user', content: options.prompt }],
    }),
  });
  if (!response.ok) {
    throw new Error(`Router error: ${response.statusText}`);
  }
  const data = await response.json();
  return {
    text: data.choices[0].message.content,
    model: data.model,
    provider: data.provider || 'unknown',
    costUsd: data.cost_usd || 0.0,
    latencySec: data.latency_sec || 0.0,
  };
}
"""

    GO_SDK = """// Package ijachi provides a native Go client for ijachi-llm-router.
package ijachi

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
)

type RouterClient struct {
	BaseURL string
}

func NewClient(baseURL string) *RouterClient {
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8000"
	}
	return &RouterClient{BaseURL: baseURL}
}

func (c *RouterClient) Route(prompt string, priority string) (string, error) {
	payload := map[string]interface{}{
		"model": priority,
		"messages": []map[string]string{{"role": "user", "content": prompt}},
	}
	body, _ := json.Marshal(payload)
	resp, err := http.Post(c.BaseURL+"/v1/chat/completions", "application/json", bytes.NewBuffer(body))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("router error: %s", resp.Status)
	}
	var res map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&res)
	choices := res["choices"].([]interface{})
	first := choices[0].(map[string]interface{})
	msg := first["message"].(map[string]interface{})
	return msg["content"].(string), nil
}
"""

    RUST_SDK = """//! Native Rust SDK for ijachi-llm-router.

use serde::{Deserialize, Serialize};

#[derive(Serialize)]
struct ChatMessage {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
}

pub struct RouterClient {
    base_url: String,
}

impl RouterClient {
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url.unwrap_or("http://127.0.0.1:8000").to_string(),
        }
    }
}
"""

    def export_sdk(self, language: str = "typescript", output_dir: Path | str | None = None) -> str:
        output_dir = Path(output_dir or Path.cwd()).resolve()
        lang = language.lower()

        if lang in {"typescript", "ts", "js", "nodejs"}:
            target_file = output_dir / "ijachi-llm-router.ts"
            target_file.write_text(self.TYPESCRIPT_SDK, encoding="utf-8")
            return f"Successfully exported TypeScript SDK to '{target_file.name}'."
        elif lang == "go":
            target_file = output_dir / "router.go"
            target_file.write_text(self.GO_SDK, encoding="utf-8")
            return f"Successfully exported Go SDK to '{target_file.name}'."
        elif lang in {"rust", "rs"}:
            target_file = output_dir / "lib.rs"
            target_file.write_text(self.RUST_SDK, encoding="utf-8")
            return f"Successfully exported Rust SDK to '{target_file.name}'."
        else:
            raise ValueError(f"Unsupported SDK language: '{language}'. Choose 'typescript', 'go', or 'rust'.")
