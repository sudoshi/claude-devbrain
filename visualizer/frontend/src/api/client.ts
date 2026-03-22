import axios from "axios";

const apiClient = axios.create({ baseURL: "/api" });

export default apiClient;

// ── Types ────────────────────────────────────────────────────────────────────

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type Metadata = Record<string, Json>;

export interface Project {
  name: string;
  collections: Array<{ name: string; type: string; count: number }>;
  total_vectors: number;
}

export interface CollectionSummary {
  name: string;
  count?: number;
  metadata?: Record<string, Json>;
}

export interface MetadataFacet {
  key: string;
  values: Array<{ label: string; count: number }>;
}

export interface SampleRecord {
  id: string;
  document?: string | null;
  metadata?: Metadata | null;
  embedding?: number[] | null;
}

export interface CollectionOverview {
  name: string;
  count: number;
  dimension?: number | null;
  metadataKeys: string[];
  facets: MetadataFacet[];
  sampleRecords: SampleRecord[];
  collectionMetadata?: Record<string, Json>;
}

export interface QueryResultItem {
  id: string;
  distance?: number | null;
  document?: string | null;
  metadata?: Metadata | null;
}

export interface QueryResponse {
  items: QueryResultItem[];
  elapsedMs?: number;
}

export interface QueryInput {
  collectionName: string;
  queryText: string;
  nResults: number;
  where?: Record<string, Json> | null;
  whereDocument?: Record<string, Json> | null;
}

export interface ProjectedPoint3D {
  id: string;
  x: number;
  y: number;
  z: number;
  metadata: Record<string, unknown>;
  cluster_id: number;
}

export interface ClusterInfo {
  id: number;
  label: string;
  centroid: [number, number, number];
  size: number;
}

export interface QualityReport {
  outlier_ids: string[];
  duplicate_pairs: [string, string][];
  orphan_ids: string[];
}

export interface ProjectionStats {
  total_vectors: number;
  sampled: number;
  projection_time_ms: number;
}

export interface ProjectionResponse {
  points: ProjectedPoint3D[];
  clusters: ClusterInfo[];
  quality: QualityReport;
  stats: ProjectionStats;
}

export interface ProjectionRequest {
  sample_size: number;
  method: "pca-umap";
  dimensions: 2 | 3;
}

// ── API Functions ────────────────────────────────────────────────────────────

export const fetchProjects = () =>
  apiClient.get<Project[]>("/projects").then((r) => r.data);

export const fetchCollections = () =>
  apiClient.get<CollectionSummary[]>("/collections").then((r) => r.data);

export const fetchCollectionOverview = (name: string, includeEmbeddings = false) =>
  apiClient
    .get<CollectionOverview>(`/collections/${encodeURIComponent(name)}/overview`, {
      params: includeEmbeddings ? { include_embeddings: true } : undefined,
    })
    .then((r) => r.data);

export const queryCollection = (input: QueryInput) =>
  apiClient.post<QueryResponse>("/query", input).then((r) => r.data);

export const fetchProjection = (
  name: string,
  request: ProjectionRequest,
  signal?: AbortSignal,
) =>
  apiClient
    .post<ProjectionResponse>(`/collections/${encodeURIComponent(name)}/project`, request, {
      signal,
      timeout: 130_000,
    })
    .then((r) => r.data);
