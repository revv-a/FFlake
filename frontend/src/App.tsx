
import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './App.css'

const API = 'http://127.0.0.1:8000'

type GraphNode = {
  id: string
  name: string
  kind?: string
  risk?: number
}

type GraphEdge = {
  id: string
  kind?: string
  name?: string
  risk?: number
  reason?: string
}

type GraphPath = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  hops?: number
  risk_score?: number
  risk_band?: string
}

type CandidateFix = {
  edge_id: string
  relationship?: string
  relationship_kind?: string
  risk?: number
  paths_blocked?: number
  remaining_path_count_after_simulated_cut?: number
  simulation_only?: boolean
}

type Analysis = {
  source: string
  target: string
  finding?: string
  baseline_path_count: number
  paths: GraphPath[]
  candidate_fixes: CandidateFix[]
  claim_boundary?: string
}

type Verification = {
  source: string
  target: string
  cut_edge_id: string
  baseline_path_count: number
  remaining_path_count: number
  verified_in_simulation: boolean
  simulation_only: boolean
  remaining_paths: GraphPath[]
  important?: string
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : JSON.stringify(data.detail ?? data),
    )
  }

  return data as T
}

function App() {
  const [health, setHealth] = useState(false)
  const [source, setSource] = useState('external-bot')
  const [target, setTarget] = useState('prod-secrets')
  const [paths, setPaths] = useState<GraphPath[]>([])
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [verification, setVerification] = useState<Verification | null>(null)
  const [selectedEdge, setSelectedEdge] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function runAction(label: string, action: () => Promise<void>) {
    setBusy(label)
    setError('')
    setNotice('')

    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  async function checkHealth() {
    await runAction('health', async () => {
      const result = await request<{ ok: boolean }>('/api/graph-hacks/health')
      setHealth(result.ok)
    })
  }

  useEffect(() => {
    void checkHealth()
  }, [])

  async function seedGraph() {
    await runAction('seed', async () => {
      const result = await request<{ seeded: boolean; nodes: number; relationships: number }>(
        '/api/graph-hacks/demo/seed',
        { method: 'POST' },
      )
      setPaths([])
      setAnalysis(null)
      setVerification(null)
      setSelectedEdge('')
      setNotice(`Demo graph seeded: ${result.nodes} nodes and ${result.relationships} relationships.`)
      const status = await request<{ ok: boolean }>('/api/graph-hacks/health')
      setHealth(status.ok)
    })
  }

  async function discoverPaths() {
    await runAction('paths', async () => {
      const query = new URLSearchParams({ source, target })
      const result = await request<{ paths: GraphPath[] }>(
        `/api/graph-hacks/paths?${query.toString()}`,
      )
      setPaths(result.paths ?? [])
      setVerification(null)
    })
  }

  async function analyzePaths() {
    await runAction('analyze', async () => {
      const result = await request<Analysis>('/api/graph-hacks/analyze', {
        method: 'POST',
        body: JSON.stringify({ source, target }),
      })

      setAnalysis(result)
      setPaths(result.paths ?? [])
      setVerification(null)
      setSelectedEdge(result.candidate_fixes?.[0]?.edge_id ?? '')
    })
  }

  async function verifyFix() {
    if (!selectedEdge) {
      setError('Select a candidate edge before verifying the simulation.')
      return
    }

    await runAction('verify', async () => {
      const result = await request<Verification>('/api/graph-hacks/verify', {
        method: 'POST',
        body: JSON.stringify({
          source,
          target,
          cut_edge_id: selectedEdge,
        }),
      })
      setVerification(result)
    })
  }

  const currentPath = paths[0] ?? analysis?.paths?.[0] ?? null

  const graph = useMemo(() => {
    if (!currentPath) {
      return { nodes: [] as Node[], edges: [] as Edge[] }
    }

    const graphNodes: Node[] = currentPath.nodes.map((node, index) => {
      const risk = Number(node.risk ?? 0)
      const color = risk >= 8 ? '#fb7185' : risk >= 5 ? '#fbbf24' : '#60a5fa'

      return {
        id: node.id,
        position: { x: index * 225, y: index % 2 === 0 ? 45 : 150 },
        data: {
          label: (
            <div className="graph-node-content">
              <strong>{node.name}</strong>
              <span>{node.kind ?? 'entity'} · Risk {risk}</span>
            </div>
          ),
        },
        style: {
          width: 185,
          minHeight: 76,
          borderRadius: 12,
          border: `1px solid ${color}`,
          background: '#171b28',
          color: '#f0f2fa',
          padding: 10,
          boxShadow: `0 0 18px ${color}18`,
        },
      }
    })

    const graphEdges: Edge[] = currentPath.edges.map((edge, index) => {
      const removedInSimulation =
        verification?.verified_in_simulation &&
        edge.id === verification.cut_edge_id

      const risk = Number(edge.risk ?? 0)
      const color = removedInSimulation
        ? '#fb7185'
        : risk >= 8
          ? '#fb7185'
          : risk >= 5
            ? '#fbbf24'
            : '#60a5fa'

      return {
        id: edge.id,
        source: currentPath.nodes[index]?.id ?? '',
        target: currentPath.nodes[index + 1]?.id ?? '',
        label: edge.kind ?? edge.name ?? edge.id,
        animated: !removedInSimulation,
        style: {
          stroke: color,
          strokeWidth: edge.id === selectedEdge ? 4 : 2,
          strokeDasharray: removedInSimulation ? '6 5' : undefined,
        },
        labelStyle: { fill: '#c5cbe0', fontSize: 10 },
        labelBgStyle: { fill: '#10131d', fillOpacity: 0.95 },
        labelBgPadding: [5, 3] as [number, number],
        markerEnd: { type: 'arrowclosed' as const, color },
      }
    })

    return { nodes: graphNodes, edges: graphEdges }
  }, [currentPath, selectedEdge, verification])

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">F</div>
          <div>
            <strong>FFlake</strong>
            <span>GRAPH INTELLIGENCE</span>
          </div>
        </div>

        <div className="side-label">WORKSPACE</div>
        <div className="nav-item active">◈ <span>Graph investigation</span></div>
        <div className="nav-item">⌘ <span>Capability paths</span></div>
        <div className="nav-item">⛨ <span>Safety & verification</span></div>

        <div className="sidebar-bottom">
          <div className="status-line">
            <span className={`status-dot ${health ? 'online' : ''}`} />
            <span>{health ? 'Graph connected' : 'Graph unavailable'}</span>
          </div>
          <span className="muted small">FalkorDB · Local workspace</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">AGENT SAFETY WORKSPACE</div>
            <h1>Capability Path Investigator</h1>
            <p>Discover risky reachability. Investigate evidence. Verify proposed changes.</p>
          </div>
          <button className="button secondary" onClick={checkHealth} disabled={!!busy}>
            ↻ Refresh status
          </button>
        </header>

        <div className="connection-banner">
          <div className="connection-icon">◈</div>
          <div className="connection-copy">
            <strong>{health ? 'FalkorDB is reachable' : 'Graph connection unavailable'}</strong>
            <span>{health ? 'Live graph health check passed.' : 'Check the backend and FalkorDB container.'}</span>
          </div>
          <span className={`pill ${health ? 'pill-green' : 'pill-neutral'}`}>
            {health ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>

        {error && (
          <div className="error-banner">
            <strong>Request failed</strong>
            <span>{error}</span>
            <button className="text-button" onClick={() => setError('')}>Dismiss</button>
          </div>
        )}

        {notice && <div className="notice-banner">{notice}</div>}

        <section className="panel investigation-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">INVESTIGATION CONFIGURATION</div>
              <h2>Trace a capability path</h2>
            </div>
            <button className="button secondary" onClick={seedGraph} disabled={!!busy}>
              {busy === 'seed' ? 'Seeding…' : '↻ Seed demo graph'}
            </button>
          </div>

          <div className="query-grid">
            <label>
              <span>STARTING ENTITY</span>
              <input value={source} onChange={e => setSource(e.target.value)} />
            </label>
            <div className="path-arrow">→</div>
            <label>
              <span>TARGET ENTITY</span>
              <input value={target} onChange={e => setTarget(e.target.value)} />
            </label>
          </div>

          <div className="action-row">
            <button className="button primary" onClick={discoverPaths} disabled={!!busy || !source.trim() || !target.trim()}>
              {busy === 'paths' ? 'Searching…' : '⌕ Discover paths'}
            </button>
            <button className="button secondary" onClick={analyzePaths} disabled={!!busy || !source.trim() || !target.trim()}>
              {busy === 'analyze' ? 'Analyzing…' : '◈ Analyze risk'}
            </button>
          </div>
        </section>

        <section className="metrics-grid">
          <article className="metric-card">
            <span className="metric-label">DISCOVERED PATHS</span>
            <strong>{paths.length || analysis?.baseline_path_count || 0}</strong>
            <span className="metric-note">Matching paths returned by the graph query</span>
          </article>
          <article className="metric-card">
            <span className="metric-label">RISK SCORE</span>
            <strong className="metric-word">{currentPath?.risk_score ?? '—'}</strong>
            <span className="metric-note">{currentPath?.risk_band ?? 'Run an analysis to calculate risk'}</span>
          </article>
          <article className="metric-card">
            <span className="metric-label">SIMULATED PATHS LEFT</span>
            <strong className="metric-word">
              {verification ? verification.remaining_path_count : '—'}
            </strong>
            <span className="metric-note">
              {verification ? 'After excluding the selected edge' : 'Run verification to compare'}
            </span>
          </article>
        </section>

        <section className="panel graph-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">LIVE PATH VISUALIZATION</div>
              <h2>Capability graph</h2>
            </div>
            <div className="graph-legend">
              <span><i className="legend-dot red" /> High risk</span>
              <span><i className="legend-dot amber" /> Medium risk</span>
              <span><i className="legend-dot blue" /> Lower risk</span>
            </div>
          </div>

          {currentPath ? (
            <div className="graph-canvas">
              <ReactFlow
                nodes={graph.nodes}
                edges={graph.edges}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                minZoom={0.25}
                maxZoom={1.5}
                nodesDraggable
                nodesConnectable={false}
                elementsSelectable
              >
                <Background color="#34394a" gap={22} />
                <MiniMap
                  nodeColor={node => {
                    const risk = Number(
                      (currentPath.nodes.find(item => item.id === node.id)?.risk) ?? 0,
                    )
                    return risk >= 8 ? '#fb7185' : risk >= 5 ? '#fbbf24' : '#60a5fa'
                  }}
                  maskColor="#090b10bb"
                />
                <Controls />
              </ReactFlow>
            </div>
          ) : (
            <div className="empty-state">
              <span className="empty-icon">⌕</span>
              <strong>No graph loaded yet</strong>
              <p>Discover paths or analyze risk to visualize the returned graph evidence.</p>
            </div>
          )}

          <p className="notice">
            The canvas visualizes the first path returned by the API. It is evidence of graph reachability,
            not proof of exploitability.
          </p>
        </section>

        <section className="results-grid">
          <article className="panel result-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">REMEDIATION PLANNING</div>
                <h2>Candidate interventions</h2>
              </div>
              <span className="pill pill-purple">SIMULATION ONLY</span>
            </div>

            {analysis?.candidate_fixes?.length ? (
              <>
                <label className="edge-picker">
                  <span>SELECT EDGE TO SIMULATE</span>
                  <select
                    value={selectedEdge}
                    onChange={e => setSelectedEdge(e.target.value)}
                  >
                    {analysis.candidate_fixes.map(candidate => (
                      <option key={candidate.edge_id} value={candidate.edge_id}>
                        {candidate.edge_id} · blocks {candidate.paths_blocked ?? 0} path(s)
                      </option>
                    ))}
                  </select>
                </label>

                <div className="candidate-list">
                  {analysis.candidate_fixes.map(candidate => (
                    <button
                      className={`candidate-card ${selectedEdge === candidate.edge_id ? 'selected' : ''}`}
                      key={candidate.edge_id}
                      onClick={() => setSelectedEdge(candidate.edge_id)}
                    >
                      <div className="candidate-title">
                        <strong>{candidate.edge_id}</strong>
                        <span className="risk-chip">Risk {candidate.risk ?? '—'}</span>
                      </div>
                      <span>{candidate.relationship ?? candidate.relationship_kind}</span>
                      <small>
                        {candidate.paths_blocked ?? 0} path(s) blocked in simulation ·{' '}
                        {candidate.remaining_path_count_after_simulated_cut ?? '—'} remaining
                      </small>
                    </button>
                  ))}
                </div>

                <button className="button primary full-width" onClick={verifyFix} disabled={!!busy || !selectedEdge}>
                  {busy === 'verify' ? 'Verifying…' : '✓ Verify simulated fix'}
                </button>
              </>
            ) : (
              <div className="empty-state">
                <strong>Analysis awaits</strong>
                <p>Run Analyze risk to rank candidate edges for simulation.</p>
              </div>
            )}
          </article>

          <article className="panel result-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">VERIFICATION EVIDENCE</div>
                <h2>Before and after</h2>
              </div>
              <span className={`pill ${verification?.verified_in_simulation ? 'pill-green' : 'pill-neutral'}`}>
                {verification ? (verification.verified_in_simulation ? 'NO PATH IN SIMULATION' : 'PATH REMAINS') : 'NOT RUN'}
              </span>
            </div>

            {verification ? (
              <>
                <div className="comparison-grid">
                  <div>
                    <span>BASELINE PATHS</span>
                    <strong>{verification.baseline_path_count}</strong>
                  </div>
                  <div>
                    <span>SIMULATED REMAINING</span>
                    <strong>{verification.remaining_path_count}</strong>
                  </div>
                </div>
                <pre className="json-result">{JSON.stringify(verification, null, 2)}</pre>
                <p className="notice">
                  Simulation only. No relationship, permission, or production resource was changed.
                </p>
              </>
            ) : (
              <div className="empty-state">
                <strong>Waiting for verification</strong>
                <p>Select a candidate edge and run the simulation to compare path counts.</p>
              </div>
            )}
          </article>
        </section>

        <footer className="footer">
          <span>FFlake · Graph-native context for AI agents</span>
          <span>Evidence first · Human-reviewed actions</span>
        </footer>
      </section>
    </main>
  )
}

export default App
