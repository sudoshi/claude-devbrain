import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Search,
  Database,
  Loader2,
  AlertCircle,
  BarChart3,
  Eye,
  RefreshCw,
  Clock,
  X,
  Brain,
  FolderOpen,
} from "lucide-react";
import {
  fetchProjects,
  fetchCollections,
  fetchCollectionOverview,
  queryCollection,
  type Project,
  type CollectionSummary,
  type CollectionOverview,
  type QueryResponse,
  type MetadataFacet,
  type SampleRecord,
  type Json,
} from "./api/client";
import VectorExplorer from "./components/vector-explorer/VectorExplorer";

const TABS = [
  { key: "overview" as const, label: "Overview", icon: BarChart3 },
  { key: "search" as const, label: "Retrieval", icon: Eye },
] as const;

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [selectedCollection, setSelectedCollection] = useState("");
  const [overview, setOverview] = useState<CollectionOverview | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "search">("overview");
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<QueryResponse | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [nResults, setNResults] = useState(8);
  const [queryHistory, setQueryHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  // Load projects on mount
  useEffect(() => {
    Promise.all([fetchProjects(), fetchCollections()])
      .then(([proj, cols]) => {
        setProjects(proj);
        setCollections(cols);
        if (proj.length > 0) {
          setSelectedProject(proj[0].name);
          if (proj[0].collections.length > 0) {
            setSelectedCollection(proj[0].collections[0].name);
          }
        }
      })
      .catch((e) => setError(normalizeError(e)))
      .finally(() => setLoadingProjects(false));
  }, []);

  // Filter collections for selected project
  const projectCollections = useMemo(() => {
    if (!selectedProject) return collections;
    const proj = projects.find((p) => p.name === selectedProject);
    if (!proj) return collections;
    const projNames = new Set(proj.collections.map((c) => c.name));
    return collections.filter((c) => projNames.has(c.name));
  }, [selectedProject, projects, collections]);

  // Load overview when collection changes
  useEffect(() => {
    if (!selectedCollection) return;
    let cancelled = false;
    setLoadingOverview(true);
    setError(null);
    setSearchResults(null);

    fetchCollectionOverview(selectedCollection)
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((e) => {
        if (!cancelled) setError(normalizeError(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingOverview(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCollection]);

  // Auto-select first collection when project changes
  useEffect(() => {
    if (!selectedProject) return;
    const proj = projects.find((p) => p.name === selectedProject);
    if (proj && proj.collections.length > 0) {
      setSelectedCollection(proj.collections[0].name);
    }
  }, [selectedProject, projects]);

  const stats = useMemo(() => {
    if (!overview) return null;
    const sampleCount = overview.sampleRecords.length;
    const avgDocLength = sampleCount
      ? Math.round(
          overview.sampleRecords.reduce((sum, r) => sum + (r.document?.length ?? 0), 0) /
            sampleCount,
        )
      : 0;
    return {
      totalVectors: overview.count,
      sampleCount,
      dimension: overview.dimension ?? null,
      metadataFieldCount: overview.metadataKeys.length,
      avgDocLength,
    };
  }, [overview]);

  async function runQuery(queryText?: string) {
    const text = queryText ?? searchText;
    if (!selectedCollection || !text.trim()) return;
    if (queryText) setSearchText(queryText);
    setQueryLoading(true);
    setError(null);
    setShowHistory(false);
    try {
      const response = await queryCollection({
        collectionName: selectedCollection,
        queryText: text,
        nResults,
      });
      setSearchResults(response);
      setActiveTab("search");
      setQueryHistory((prev) => {
        const filtered = prev.filter((q) => q !== text.trim());
        return [text.trim(), ...filtered].slice(0, 10);
      });
    } catch (e) {
      setError(normalizeError(e));
    } finally {
      setQueryLoading(false);
    }
  }

  const handleRefresh = useCallback(() => {
    setLoadingProjects(true);
    Promise.all([fetchProjects(), fetchCollections()])
      .then(([proj, cols]) => {
        setProjects(proj);
        setCollections(cols);
      })
      .catch((e) => setError(normalizeError(e)))
      .finally(() => setLoadingProjects(false));
  }, []);

  const totalVectors = projects.reduce((sum, p) => sum + p.total_vectors, 0);

  return (
    <div className="min-h-screen bg-[#0A0A0F]">
      {/* Header */}
      <header className="border-b border-[#232328] bg-[#0E0E11]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Brain className="h-7 w-7 text-[#C9A227]" />
            <div>
              <h1 className="text-lg font-bold text-[#F0EDE8]">DevBrain Visualizer</h1>
              <p className="text-xs text-[#5A5650]">
                {totalVectors.toLocaleString()} vectors across {projects.length} projects
              </p>
            </div>
          </div>
          <button
            onClick={handleRefresh}
            disabled={loadingProjects}
            className="rounded-lg p-2 text-[#5A5650] hover:bg-[#232328] hover:text-[#F0EDE8] transition-colors disabled:opacity-40"
          >
            {loadingProjects ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-6 py-6">
        {/* Project Selector */}
        <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
          <div className="flex items-center gap-3 mb-3">
            <FolderOpen className="h-5 w-5 text-[#2DD4BF]" />
            <span className="font-semibold text-[#F0EDE8]">Projects</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {projects.map((proj) => (
              <button
                key={proj.name}
                onClick={() => setSelectedProject(proj.name)}
                className={`flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all ${
                  selectedProject === proj.name
                    ? "bg-[#C9A227]/15 text-[#C9A227] border border-[#C9A227]/30"
                    : "bg-[#151518] text-[#8A857D] border border-[#232328] hover:bg-[#1a1a1f] hover:text-[#C5C0B8]"
                }`}
              >
                <span className="capitalize">{proj.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs ${
                    selectedProject === proj.name
                      ? "bg-[#C9A227]/20 text-[#C9A227]"
                      : "bg-[#232328] text-[#5A5650]"
                  }`}
                >
                  {proj.total_vectors.toLocaleString()}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* 3D Semantic Map */}
        {overview && overview.count > 0 && (
          <VectorExplorer collectionName={selectedCollection} overview={overview} />
        )}

        {/* Collection Studio Panel */}
        <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <Database className="h-5 w-5 text-[#2DD4BF]" />
              <div>
                <p className="font-semibold text-[#F0EDE8]">Collection Studio</p>
                <p className="mt-0.5 text-sm text-[#8A857D]">
                  Inspect vector collections and run semantic queries
                </p>
              </div>
            </div>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                projectCollections.length > 0
                  ? "bg-[#2DD4BF]/10 text-[#2DD4BF]"
                  : "bg-[#C9A227]/10 text-[#C9A227]"
              }`}
            >
              {projectCollections.length > 0
                ? `${projectCollections.length} collections`
                : "loading"}
            </span>
          </div>

          {/* Collection selector */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <select
              value={selectedCollection}
              onChange={(e) => setSelectedCollection(e.target.value)}
              className="rounded-lg border border-[#232328] bg-[#151518] px-3 py-2 text-sm text-[#E8E4DC] outline-none transition focus:border-[#C9A227]/50"
            >
              {projectCollections.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} {c.count != null ? `(${c.count.toLocaleString()})` : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Stats row */}
          {stats && (
            <div className="mt-3 grid grid-cols-4 gap-2">
              {[
                { label: "Vectors", value: fmt(stats.totalVectors) },
                { label: "Sampled", value: fmt(stats.sampleCount) },
                { label: "Dimensions", value: stats.dimension ? fmt(stats.dimension) : "--" },
                { label: "Meta Fields", value: fmt(stats.metadataFieldCount) },
              ].map((cell) => (
                <div
                  key={cell.label}
                  className="rounded-lg bg-[#151518] px-2.5 py-2 text-center"
                >
                  <div className="text-sm font-medium text-[#F0EDE8] font-mono">
                    {cell.value}
                  </div>
                  <div className="text-xs text-[#5A5650]">{cell.label}</div>
                </div>
              ))}
            </div>
          )}

          {loadingOverview && (
            <div className="mt-3 flex items-center gap-2 text-sm text-[#8A857D]">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading collection data...
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[#E85A6B]/20 bg-[#E85A6B]/5 px-4 py-3 text-sm text-[#E85A6B]">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        {/* Empty collection */}
        {overview && overview.count === 0 && (
          <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
            <div className="flex flex-col items-center gap-3 py-6 text-center">
              <Database className="h-8 w-8 text-[#5A5650]" />
              <div>
                <p className="text-sm font-medium text-[#C5C0B8]">This collection is empty</p>
                <p className="mt-1 text-sm text-[#5A5650]">
                  Run the ingestion script to populate "{selectedCollection}" with documents.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Tab bar + search + content */}
        {overview && overview.count > 0 && (
          <div className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex gap-1 rounded-lg border border-[#232328] bg-[#0E0E11] p-1">
                {TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
                      activeTab === tab.key
                        ? "bg-[#C9A227]/15 text-[#C9A227]"
                        : "text-[#5A5650] hover:text-[#8A857D]"
                    }`}
                  >
                    <tab.icon size={14} />
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <div className="relative flex-1 lg:w-72">
                  <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#5A5650]" />
                  <input
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runQuery()}
                    onFocus={() => queryHistory.length > 0 && setShowHistory(true)}
                    onBlur={() => setTimeout(() => setShowHistory(false), 200)}
                    placeholder="Semantic query..."
                    className="w-full rounded-lg border border-[#232328] bg-[#0E0E11] py-2 pl-8 pr-2.5 text-sm text-[#E8E4DC] outline-none transition focus:border-[#C9A227]/50"
                  />
                  {showHistory && queryHistory.length > 0 && (
                    <div className="absolute left-0 top-full z-30 mt-1 w-full rounded-lg border border-[#232328] bg-[#151518] shadow-xl">
                      <div className="flex items-center justify-between px-2.5 py-1.5 text-xs text-[#5A5650]">
                        <span className="flex items-center gap-1">
                          <Clock size={10} /> Recent queries
                        </span>
                        <button
                          onMouseDown={(e) => {
                            e.preventDefault();
                            setQueryHistory([]);
                            setShowHistory(false);
                          }}
                          className="text-[#5A5650] hover:text-[#E85A6B]"
                        >
                          <X size={10} />
                        </button>
                      </div>
                      {queryHistory.map((q) => (
                        <button
                          key={q}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            runQuery(q);
                          }}
                          className="block w-full px-2.5 py-1.5 text-left text-sm text-[#C5C0B8] hover:bg-[#232328] truncate"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-xs text-[#5A5650]">K:</span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={nResults}
                    onChange={(e) =>
                      setNResults(Math.max(1, Math.min(50, Number(e.target.value) || 1)))
                    }
                    className="w-12 rounded-lg border border-[#232328] bg-[#0E0E11] px-1.5 py-2 text-center text-sm text-[#E8E4DC] outline-none transition focus:border-[#C9A227]/50"
                  />
                </div>
                <button
                  onClick={() => runQuery()}
                  disabled={queryLoading || !selectedCollection || !searchText.trim()}
                  className="flex items-center gap-1.5 rounded-lg bg-[#C9A227] px-4 py-2 text-sm font-medium text-[#0A0A0F] transition hover:bg-[#C9A227]/90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {queryLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Search className="h-3.5 w-3.5" />
                  )}
                  Query
                </button>
              </div>
            </div>

            {activeTab === "overview" && <OverviewSection overview={overview} />}
            {activeTab === "search" && (
              <SearchSection
                searchResults={searchResults}
                queryLoading={queryLoading}
                searchText={searchText}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// ── Overview Section ─────────────────────────────────────────────────────────

function OverviewSection({ overview }: { overview: CollectionOverview }) {
  return (
    <div className="space-y-4">
      {overview.facets.length > 0 && (
        <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
          <h3 className="mb-3 text-base font-semibold text-[#F0EDE8]">Facet Distribution</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {overview.facets.map((facet) => (
              <FacetCard key={facet.key} facet={facet} />
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
        <h3 className="mb-3 text-base font-semibold text-[#F0EDE8]">
          Sample Records
          <span className="ml-2 text-sm font-normal text-[#5A5650]">
            ({overview.sampleRecords.length} sampled)
          </span>
        </h3>
        {overview.sampleRecords.length === 0 ? (
          <p className="text-sm text-[#5A5650]">No records in this collection.</p>
        ) : (
          <div className="space-y-2">
            {overview.sampleRecords.slice(0, 8).map((record) => (
              <RecordCard key={record.id} record={record} />
            ))}
          </div>
        )}
      </div>

      {Object.keys(overview.collectionMetadata ?? {}).length > 0 && (
        <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
          <h3 className="mb-3 text-base font-semibold text-[#F0EDE8]">Collection Metadata</h3>
          <div className="space-y-1.5">
            {Object.entries(overview.collectionMetadata ?? {}).map(([k, v]) => (
              <div
                key={k}
                className="flex items-center justify-between rounded-lg bg-[#151518] px-2.5 py-1.5 text-sm"
              >
                <span className="font-mono text-[#2DD4BF]">{k}</span>
                <span className="text-[#8A857D]">
                  {typeof v === "string" ? v : JSON.stringify(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Search Section ───────────────────────────────────────────────────────────

function SearchSection({
  searchResults,
  queryLoading,
  searchText,
}: {
  searchResults: QueryResponse | null;
  queryLoading: boolean;
  searchText: string;
}) {
  if (!searchResults && !queryLoading) {
    return (
      <div className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4">
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <Search className="h-6 w-6 text-[#5A5650]" />
          <p className="text-sm text-[#8A857D]">
            Enter a query above and click Query to inspect retrieval results.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {searchResults && (
        <div className="flex items-center gap-3 text-sm text-[#8A857D]">
          <span>
            Query: <span className="text-[#E8E4DC]">{searchText}</span>
          </span>
          <span className="rounded-lg bg-[#151518] px-2 py-0.5 font-mono text-[#2DD4BF]">
            {searchResults.elapsedMs ?? "--"} ms
          </span>
          <span>{searchResults.items.length} results</span>
        </div>
      )}

      {queryLoading && (
        <div className="flex items-center gap-2 text-sm text-[#8A857D]">
          <Loader2 className="h-3 w-3 animate-spin" />
          Querying...
        </div>
      )}

      {(searchResults?.items ?? []).map((item, index) => (
        <div
          key={`${item.id}_${index}`}
          className="rounded-xl border border-[#232328] bg-[#0E0E11] p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="rounded-lg bg-[#2DD4BF]/15 px-1.5 py-0.5 text-xs font-medium text-[#2DD4BF]">
                  #{index + 1}
                </span>
                <span className="truncate font-mono text-xs text-[#5A5650]">{item.id}</span>
              </div>
              <p className="line-clamp-3 text-sm leading-relaxed text-[#C5C0B8]">
                {item.document || "No document returned."}
              </p>
            </div>
            <div className="shrink-0 rounded-lg bg-[#151518] px-2.5 py-1.5 text-center">
              <div className="text-xs text-[#5A5650]">distance</div>
              <div className="font-mono text-sm font-medium text-[#F0EDE8]">
                {typeof item.distance === "number" ? item.distance.toFixed(4) : "--"}
              </div>
            </div>
          </div>
          {item.metadata && Object.keys(item.metadata).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(item.metadata).map(([k, v]) => (
                <MetadataTag key={k} k={k} v={v} />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Sub-Components ───────────────────────────────────────────────────────────

function FacetCard({ facet }: { facet: MetadataFacet }) {
  const max = Math.max(...facet.values.map((v) => v.count), 1);
  return (
    <div className="rounded-lg border border-[#232328] bg-[#151518] p-3">
      <div className="mb-2 text-sm font-medium text-[#C5C0B8]">{facet.key}</div>
      <div className="space-y-2">
        {facet.values.map((entry) => (
          <div key={entry.label}>
            <div className="mb-0.5 flex items-center justify-between text-xs text-[#5A5650]">
              <span className="truncate">{entry.label}</span>
              <span>{entry.count}</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-[#232328]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[#9B1B30] to-[#2DD4BF]"
                style={{ width: `${(entry.count / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RecordCard({ record }: { record: SampleRecord }) {
  return (
    <div className="rounded-lg border border-[#232328] bg-[#151518] p-3">
      <div className="mb-1.5 font-mono text-xs text-[#2DD4BF] truncate">{record.id}</div>
      <p className="line-clamp-2 text-sm leading-relaxed text-[#8A857D]">
        {record.document || "No document text available."}
      </p>
      {record.metadata && Object.keys(record.metadata).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {Object.entries(record.metadata)
            .slice(0, 5)
            .map(([k, v]) => (
              <MetadataTag key={k} k={k} v={v} />
            ))}
        </div>
      )}
    </div>
  );
}

function MetadataTag({ k, v }: { k: string; v: Json }) {
  return (
    <span className="inline-flex rounded-md bg-[#232328] px-1.5 py-0.5 text-xs text-[#5A5650]">
      <span className="text-[#8A857D]">{k}:</span>
      <span className="ml-0.5 truncate max-w-[180px]">
        {typeof v === "string" ? v : JSON.stringify(v)}
      </span>
    </span>
  );
}

// ── Utilities ────────────────────────────────────────────────────────────────

function normalizeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error !== null && "response" in error) {
    const resp = error as { response?: { data?: { error?: string; message?: string } } };
    return resp.response?.data?.error ?? resp.response?.data?.message ?? "Unknown error.";
  }
  return "Unknown error.";
}

function fmt(value: number): string {
  return new Intl.NumberFormat().format(value);
}
