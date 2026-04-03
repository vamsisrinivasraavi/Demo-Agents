import { useState } from "react";
import { ingestionApi } from "../../api/client";
import toast from "react-hot-toast";
import {
  Database,
  TestTube,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";

const INITIAL = {
  name: "",
  description: "",
  host: "localhost",
  port: "1433",
  database: "",
  username: "",
  password: "",
  driver: "ODBC Driver 18 for SQL Server",
  trust_server_certificate: true,
  qdrant_collection: "",
  embedding_model: "text-embedding-3-small",
  chunk_strategy: "table_level",
  sql_top_k: "5",
};

export default function IngestForm({ onSuccess }) {
  const [form, setForm] = useState(INITIAL);
  const [testing, setTesting] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const set = (field) => (e) =>
    setForm((f) => ({
      ...f,
      [field]: e.target?.type === "checkbox" ? e.target.checked : e.target.value,
    }));

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await ingestionApi.test({
        host: form.host,
        port: Number(form.port),
        database: form.database,
        username: form.username,
        password: form.password,
        driver: form.driver,
        trust_server_certificate: form.trust_server_certificate,
      });
      setTestResult(data);
      if (data.success) toast.success(`Connected! Found ${data.tables_found} tables`);
      else toast.error(data.message);
    } catch (err) {
      toast.error(err.response?.data?.error?.message || "Connection test failed");
    } finally {
      setTesting(false);
    }
  };

  const handleIngest = async (e) => {
    e.preventDefault();
    setIngesting(true);
    try {
      const { data } = await ingestionApi.create({
        name: form.name,
        description: form.description,
        sql_connection: {
          host: form.host,
          port: Number(form.port),
          database: form.database,
          username: form.username,
          password: form.password,
          driver: form.driver,
          trust_server_certificate: form.trust_server_certificate,
        },
        qdrant_collection: form.qdrant_collection,
        embedding_model: form.embedding_model,
        chunk_strategy: form.chunk_strategy,
        sql_top_k: Number(form.sql_top_k),
      });
      toast.success("Schema ingested successfully!");
      onSuccess?.(data);
      setForm(INITIAL);
      setTestResult(null);
    } catch (err) {
      toast.error(err.response?.data?.error?.message || "Ingestion failed");
    } finally {
      setIngesting(false);
    }
  };

  return (
    <form onSubmit={handleIngest} className="space-y-6">
      {/* Config Name */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">Config Name</label>
          <input className="input-field" value={form.name} onChange={set("name")} placeholder="Production ERP Schema" required />
        </div>
        <div>
          <label className="label">Qdrant Collection</label>
          <input className="input-field font-mono" value={form.qdrant_collection} onChange={set("qdrant_collection")} placeholder="erp_schema_v1" required />
        </div>
      </div>

      {/* SQL Connection */}
      <div>
        <h4 className="flex items-center gap-2 text-sm font-semibold text-surface-700 mb-3">
          <Database className="h-4 w-4" /> SQL Server Connection
        </h4>
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2">
            <label className="label">Host</label>
            <input className="input-field" value={form.host} onChange={set("host")} required />
          </div>
          <div>
            <label className="label">Port</label>
            <input className="input-field" type="number" value={form.port} onChange={set("port")} required />
          </div>
          <div>
            <label className="label">Database</label>
            <input className="input-field" value={form.database} onChange={set("database")} placeholder="AdventureWorks" required />
          </div>
          <div>
            <label className="label">Username</label>
            <input className="input-field" value={form.username} onChange={set("username")} required />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input-field" type="password" value={form.password} onChange={set("password")} required />
          </div>
        </div>

        {/* Test button */}
        <div className="mt-3 flex items-center gap-3">
          <button type="button" onClick={handleTest} disabled={testing || !form.host || !form.database} className="btn-secondary">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube className="h-4 w-4" />}
            Test Connection
          </button>
          {testResult && (
            <span className={`flex items-center gap-1 text-sm ${testResult.success ? "text-emerald-600" : "text-red-600"}`}>
              {testResult.success ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {testResult.success ? `${testResult.tables_found} tables found` : "Failed"}
            </span>
          )}
        </div>
      </div>

      {/* Embedding Settings */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="label">Embedding Model</label>
          <select className="input-field" value={form.embedding_model} onChange={set("embedding_model")}>
            <option value="text-embedding-3-small">text-embedding-3-small</option>
            <option value="text-embedding-3-large">text-embedding-3-large</option>
          </select>
        </div>
        <div>
          <label className="label">Chunk Strategy</label>
          <select className="input-field" value={form.chunk_strategy} onChange={set("chunk_strategy")}>
            <option value="table_level">Table Level</option>
            <option value="column_level">Column Level</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </div>
        <div>
          <label className="label">SQL Top K</label>
          <input className="input-field" type="number" min="1" max="20" value={form.sql_top_k} onChange={set("sql_top_k")} />
        </div>
      </div>

      {/* Submit */}
      <button type="submit" disabled={ingesting} className="btn-primary w-full">
        {ingesting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Ingesting Schema...
          </>
        ) : (
          <>
            <Database className="h-4 w-4" /> Start Ingestion
          </>
        )}
      </button>
    </form>
  );
}