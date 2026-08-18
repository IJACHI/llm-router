# Pricing & Subscription Plans 💳

`ijachi-llm-router` is built on an **Open Core** model: the core engine is free and open-source under the MIT license, while advanced cloud features, commercial licensing, and managed services are available through flexible paid tiers.

---

## Plan Comparison

| Feature | **Community** <br> *(Open Source)* | **Pro** <br> *(Hosted SaaS)* | **Enterprise** <br> *(Commercial / Custom)* |
|---|:---:|:---:|:---:|
| **Price** | **Free ($0)** | **$19 / month** | **Custom** |
| **License** | MIT License | Hosted API / SaaS | Commercial Dual License |
| **CLI & Python Library** | ✅ Included | ✅ Included | ✅ Included |
| **Prompt Routing Engine** | ✅ Local / Self-hosted | ✅ Managed Cloud API | ✅ Self-hosted or Dedicated |
| **Circuit Breakers & Fallbacks** | ✅ Standard | ✅ Real-time Global Breakers | ✅ Custom SLA Guarantees |
| **Local Models (Ollama)** | ✅ Supported | N/A (Cloud providers) | ✅ Hybrid Cloud + Local |
| **Cost & Usage Tracking** | ✅ CLI Stats (`history.jsonl`) | ✅ Web Dashboard & Telemetry | ✅ Enterprise Audit Logs & Export |
| **Cost Capping & Alerts** | Local CLI flags | Webhook Alerts + Hard Caps | Custom Budget Rules per Team |
| **Support** | Community (GitHub Issues) | Priority Email Support | 24/7 SLA & Dedicated Slack |
| **Custom Classifier Models** | Manual training | Auto-optimizing Classifier | Bespoke Fine-tuned Classifiers |

---

## Tier Details

### 🟢 1. Community Tier (Free & Open Source)
Designed for developers, hackers, researchers, and non-commercial projects.

- **Cost**: $0 (Free forever)
- **License**: [MIT License](LICENSE)
- **Includes**:
  - Full access to `ijachi-llm-router` CLI (`ijachi-router`, `ijr`) and Python SDK (`ijachi_router`).
  - TF-IDF + Logistic Regression prompt classifier for intent detection.
  - Multi-provider support across 20 major LLM providers (OpenAI, Anthropic, Gemini, DeepSeek, Kimi, Qwen, Groq, Mistral, AWS Bedrock, Azure OpenAI, Cerebras, SambaNova, Fireworks, Hugging Face, Cohere, Perplexity, Together, OpenRouter, Custom, Ollama).
  - Built-in circuit breakers and automatic provider fallbacks.
  - Local usage logging (`~/.ijachi-llmr/history.jsonl`).

---

### 🔵 2. Pro Tier (Hosted Cloud API & Managed Service)
Designed for individual developers and startups wanting a zero-maintenance cloud router with analytics.

- **Cost**: $19 / month (or usage-based billing)
- **Payment Link**: [**Pay via Paystack**](https://paystack.shop/pay/enlqpvzflw)
- **Includes**:
  - **Zero Setup**: Drop-in REST API endpoint replacing complex local config.
  - **Cloud Analytics Dashboard**: Live metrics on latency, cost savings, token usage, and top categories.
  - **Budget Alerts**: Receive webhooks or emails when spend approaches your custom monthly threshold.
  - **Priority Support**: Direct email support with guaranteed response times.

👉 **Ready to upgrade to Pro?** [Complete your payment on Paystack](https://paystack.shop/pay/enlqpvzflw) and contact support with your transaction reference to activate your Pro key.

---

### 🟣 3. Enterprise & Commercial Licensing
Designed for companies embedding `ijachi-llm-router` inside closed-source proprietary products or requiring compliance guarantees.

- **Cost**: Custom annual subscription
- **License**: [Commercial License](COMMERCIAL_LICENSE.md)
- **Includes**:
  - Proprietary commercial license waiving open-source attribution requirements.
  - Custom LLM provider integrations (Azure OpenAI, AWS Bedrock, GCP Vertex AI, private endpoints).
  - Custom-trained classification models optimized for your enterprise domain data.
  - Multi-tenant team access, RBAC, and SOC 2 / HIPAA compliance telemetry.
  - Dedicated Solutions Engineer & 24/7 emergency SLA support.

---

## Payment & Billing Information

All subscriptions and commercial license payments are securely processed via **Paystack**.

* **Payment Link**: [`https://paystack.shop/pay/enlqpvzflw`](https://paystack.shop/pay/enlqpvzflw)
* **Accepted Payment Methods**: Credit/Debit Cards, Wire Transfers, Mobile Money, Apple Pay (via Paystack).
* **Enterprise Invoicing**: Custom purchase orders and invoice billing available upon request.

For commercial license inquiries or custom enterprise setups, please visit our [Paystack Payment Page](https://paystack.shop/pay/enlqpvzflw) or open an issue on GitHub.
