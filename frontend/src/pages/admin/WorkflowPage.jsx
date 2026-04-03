import { useState, useEffect } from "react";
import { workflowApi } from "../../api/client";
import WorkflowBuilder from "../../components/admin/WorkflowBuilder";
import toast from "react-hot-toast";
import {
  GitBranch,
  Plus,
  ChevronDown,
  Loader2,
  Trash2,
  Zap,
  ZapOff,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";

export default function WorkflowPage() {
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showBuilder, setShowBuilder] = useState(false);

  const loadWorkflows = async () => {
    try {
      const { data } = await workflowApi.listAdmin();
      setWorkflows(data.items);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadWorkflows();
  }, []);

  const handleToggle = async (wf) => {
    try {
      await workflowApi.update(wf.id, { is_active: !wf.is_active });
      toast.success(wf.is_active ? "Workflow deactivated" : "Workflow activated");
      loadWorkflows();
    } catch {
      toast.error("Failed to update");
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Deactivate this workflow?")) return;
    try {
      await workflowApi.delete(id);
      toast.success("Workflow deactivated");
      loadWorkflows();
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-surface-900">Workflows</h1>
          <p className="text-sm text-surface-400 mt-0.5">
            Configure agent pipelines for schema Q&A
          </p>
        </div>
        <button
          onClick={() => setShowBuilder((v) => !v)}
          className="btn-primary"
        >
          {showBuilder ? (
            <>
              <ChevronDown className="h-4 w-4" /> Hide Builder
            </>
          ) : (
            <>
              <Plus className="h-4 w-4" /> New Workflow
            </>
          )}
        </button>
      </div>

      {/* Builder */}
      {showBuilder && (
        <div className="card p-6 mb-6 animate-slide-up">
          <WorkflowBuilder
            onSuccess={() => {
              setShowBuilder(false);
              loadWorkflows();
            }}
          />
        </div>
      )}

      {/* Workflow List */}
      {loading ? (
        <div className="text-center py-12 text-surface-400">
          <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
          Loading...
        </div>
      ) : workflows.length === 0 ? (
        <div className="card py-12 text-center text-surface-400">
          <GitBranch className="h-8 w-8 mx-auto mb-2 opacity-40" />
          <p>No workflows yet. Create one above.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className={`card flex items-center justify-between p-4 transition-opacity ${
                !wf.is_active ? "opacity-50" : ""
              }`}
            >
              <div className="flex items-center gap-4 min-w-0">
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                    wf.is_active
                      ? "bg-brand-100 text-brand-600"
                      : "bg-surface-100 text-surface-400"
                  }`}
                >
                  <GitBranch className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <p className="font-medium text-surface-800 truncate">
                    {wf.name}
                  </p>
                  <div className="flex items-center gap-3 text-xs text-surface-400">
                    <span>{wf.agent_count} agents</span>
                    {wf.cache_enabled && (
                      <span className="flex items-center gap-1 text-amber-600">
                        <Zap className="h-3 w-3" /> Cached
                      </span>
                    )}
                    <span>{wf.is_active ? "Active" : "Inactive"}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleToggle(wf)}
                  className="rounded-md p-2 text-surface-400 hover:bg-surface-100 hover:text-surface-600 transition-colors"
                  title={wf.is_active ? "Deactivate" : "Activate"}
                >
                  {wf.is_active ? (
                    <ToggleRight className="h-5 w-5 text-brand-600" />
                  ) : (
                    <ToggleLeft className="h-5 w-5" />
                  )}
                </button>
                <button
                  onClick={() => handleDelete(wf.id)}
                  className="rounded-md p-2 text-surface-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}