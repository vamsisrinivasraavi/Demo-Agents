import { useState, useEffect } from "react";
import { ingestionApi, workflowApi } from "../../api/client";
import toast from "react-hot-toast";
import { GitBranch, Loader2, Plus } from "lucide-react";

const DEFAULT_AGENTS = [
  { type: "retrieval", enabled: true, config: { top_k: 5, score_threshold: 0.7 } },
  { type: "web_search", enabled: true, config: { trigger_on_low_confidence: true, confidence_threshold: 0.6, max_results: 3 } },
  { type: "guardrail", enabled: true, config: { check_hallucination: true, check_sql_injection: true, check_pii_exposure: true } },
];

export default function WorkflowBuilder({ onSuccess }) {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    name: "",
    description: "",
    ingestion_config_id: "",
    agents: DEFAULT_AGENTS,
    model: "gpt-4o",
    temperature: 0.2,
    max_tokens: 1024,
    enable_cache: true,
    cache_ttl: 3600,
  });

  useEffect(() => {
    ingestionApi.list().then(({ data }) => {
      const completed = data.items.filter((c) => c.status === "completed");
      setConfigs(completed);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const set = (field) => (e) =>
    setForm((f) => ({ ...f, [field]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const toggleAgent = (index) => {
    setForm((f) => {
      const agents = [...f.agents];
      agents[index] = { ...agents[index], enabled: !agents[index].enabled };
      return { ...f, agents };
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.ingestion_config_id) {
      toast.error("Select an ingestion config");
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await workflowApi.create({
        name: form.name,
        description: form.description,
        ingestion_config_id: form.ingestion_config_id,
        agents: form.agents,
        model_settings: {
          model: form.model,
          temperature: Number(form.temperature),
          max_tokens: Number(form.max_tokens),
        },
        feature_flags: {
          enable_cache: form.enable_cache,
          cache_ttl_seconds: Number(form.cache_ttl),
        },
      });
      toast.success("Workflow created!");
      onSuccess?.(data);
    } catch (err) {
      toast.error(err.response?.data?.error?.message || "Failed to create workflow");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="text-center py-8 text-surface-400">Loading configs...</div>;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">Workflow Name</label>
          <input className="input-field" value={form.name} onChange={set("name")} placeholder="ERP Schema Q&A" required />
        </div>
        <div>
          <label className="label">Ingestion Config</label>
          <select className="input-field" value={form.ingestion_config_id} onChange={set("ingestion_config_id")} required>
            <option value="">Select a completed ingestion...</option>
            {configs.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.qdrant_collection})</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="label">Description</label>
        <textarea className="input-field" rows={2} value={form.description} onChange={set("description")} placeholder="Describe what this workflow does..." />
      </div>

      {/* Agent Pipeline */}
      <div>
        <h4 className="text-sm font-semibold text-surface-700 mb-3">Agent Pipeline</h4>
        <div className="space-y-2">
          {form.agents.map((agent, i) => (
            <div key={agent.type} className={`flex items-center justify-between rounded-lg border p-3 transition-colors ${agent.enabled ? "border-brand-200 bg-brand-50/50" : "border-surface-200 bg-surface-50 opacity-60"}`}>
              <div className="flex items-center gap-3">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-200 text-[11px] font-bold text-surface-600">{i + 1}</span>
                <div>
                  <p className="text-sm font-medium text-surface-800 capitalize">{agent.type.replace("_", " ")} Agent</p>
                  <p className="text-[11px] text-surface-400">
                    {agent.type === "retrieval" && "LlamaIndex → table discovery → SQL gen → execute"}
                    {agent.type === "web_search" && "MCP-powered fallback when confidence is low"}
                    {agent.type === "guardrail" && "SQL safety + PII check + hallucination validation"}
                  </p>
                </div>
              </div>
              <label className="relative inline-flex cursor-pointer items-center">
                <input type="checkbox" checked={agent.enabled} onChange={() => toggleAgent(i)} className="peer sr-only" disabled={agent.type === "retrieval"} />
                <div className="h-5 w-9 rounded-full bg-surface-300 peer-checked:bg-brand-600 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-full" />
              </label>
            </div>
          ))}
        </div>
      </div>

      {/* Model Settings */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="label">LLM Model</label>
          <select className="input-field" value={form.model} onChange={set("model")}>
            <option value="gpt-4o">GPT-4o</option>
            <option value="gpt-4o-mini">GPT-4o Mini</option>
            <option value="gpt-4-turbo">GPT-4 Turbo</option>
          </select>
        </div>
        <div>
          <label className="label">Temperature</label>
          <input className="input-field" type="number" min="0" max="2" step="0.1" value={form.temperature} onChange={set("temperature")} />
        </div>
        <div>
          <label className="label">Max Tokens</label>
          <input className="input-field" type="number" min="128" max="16384" value={form.max_tokens} onChange={set("max_tokens")} />
        </div>
      </div>

      {/* Feature Flags */}
      <div className="flex items-center gap-6 rounded-lg border border-surface-200 bg-surface-50 px-4 py-3">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={form.enable_cache} onChange={set("enable_cache")} className="h-4 w-4 rounded border-surface-300 text-brand-600 focus:ring-brand-500" />
          Enable semantic cache
        </label>
        {form.enable_cache && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-surface-500">TTL:</span>
            <input className="input-field w-24 !py-1.5" type="number" min="60" max="86400" value={form.cache_ttl} onChange={set("cache_ttl")} />
            <span className="text-surface-400">seconds</span>
          </div>
        )}
      </div>

      <button type="submit" disabled={submitting} className="btn-primary w-full">
        {submitting ? <><Loader2 className="h-4 w-4 animate-spin" /> Creating...</> : <><Plus className="h-4 w-4" /> Create Workflow</>}
      </button>
    </form>
  );
}