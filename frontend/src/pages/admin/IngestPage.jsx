import { useState, useEffect } from "react";
import { ingestionApi } from "../../api/client";
import IngestForm from "../../components/admin/IngestForm";
import {
  Database,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Trash2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import toast from "react-hot-toast";

const STATUS_STYLES = {
  completed: "bg-emerald-100 text-emerald-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
};

const STATUS_ICONS = {
  completed: CheckCircle2,
  running: Loader2,
  pending: Clock,
  failed: XCircle,
};

export default function IngestPage() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const loadConfigs = async () => {
    try {
      const { data } = await ingestionApi.list();
      setConfigs(data.items);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfigs();
  }, []);

  const handleDelete = async (id) => {
    if (!confirm("Delete this config and its Qdrant collection?")) return;
    try {
      await ingestionApi.delete(id);
      toast.success("Deleted");
      loadConfigs();
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-surface-900">
            Schema Ingestion
          </h1>
          <p className="text-sm text-surface-400 mt-0.5">
            Connect to SQL Server and ingest schema into vector store
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="btn-primary"
        >
          {showForm ? (
            <>
              <ChevronDown className="h-4 w-4" /> Hide Form
            </>
          ) : (
            <>
              <Database className="h-4 w-4" /> New Ingestion
            </>
          )}
        </button>
      </div>

      {/* Ingest Form */}
      {showForm && (
        <div className="card p-6 mb-6 animate-slide-up">
          <IngestForm
            onSuccess={() => {
              setShowForm(false);
              loadConfigs();
            }}
          />
        </div>
      )}

      {/* Config List */}
      {loading ? (
        <div className="text-center py-12 text-surface-400">
          <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
          Loading...
        </div>
      ) : configs.length === 0 ? (
        <div className="card py-12 text-center text-surface-400">
          <Database className="h-8 w-8 mx-auto mb-2 opacity-40" />
          <p>No ingestion configs yet. Create one above.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {configs.map((config) => {
            const Icon = STATUS_ICONS[config.status] || Clock;
            return (
              <div
                key={config.id}
                className="card flex items-center justify-between p-4"
              >
                <div className="flex items-center gap-4 min-w-0">
                  <div
                    className={`flex h-9 w-9 items-center justify-center rounded-lg ${STATUS_STYLES[config.status]}`}
                  >
                    <Icon
                      className={`h-4 w-4 ${config.status === "running" ? "animate-spin" : ""}`}
                    />
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium text-surface-800 truncate">
                      {config.name}
                    </p>
                    <div className="flex items-center gap-3 text-xs text-surface-400">
                      <span className="font-mono">
                        {config.qdrant_collection}
                      </span>
                      <span>
                        {config.sql_connection?.database}@{config.sql_connection?.host}
                      </span>
                      {config.schema_stats?.tables_count > 0 && (
                        <span>
                          {config.schema_stats.tables_count} tables ·{" "}
                          {config.schema_stats.columns_count} columns
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(config.id)}
                  className="rounded-md p-2 text-surface-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}