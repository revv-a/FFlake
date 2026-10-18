
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
import './WorkflowCenter.css'

const API = (import.meta.env.VITE_API_URL || 'https://fflake-backend.onrender.com').replace(/\/$/, '')
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
  remediation_cost?: number
  cost_was_assumed?: boolean
  paths_blocked?: number
  remaining_path_count_after_simulated_cut?: number
  simulation_only?: boolean
}

type MinimumCostCut = {
  edges: CandidateFix[]
  total_remediation_cost: number
  cost_assumption_used: boolean
  simulation_only: boolean
  claim_boundary?: string
}

type Analysis = {
  source: string
  target: string
  finding?: string
  baseline_path_count: number
  paths: GraphPath[]
  candidate_fixes: CandidateFix[]
  minimum_cost_cut?: MinimumCostCut
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

type Investigation = {
  run_id: string
  timestamp: string
  request: string
  status: string
  result?: {
    decision?: { arguments?: { source?: string; target?: string } }
    result?: unknown
  }
}

type Proposal = {
  proposal_id: string
  run_id: string
  source: string
  target: string
  edge_id: string
  description: string
  status: 'pending' | 'approved' | 'rejected' | 'verified'
  created_at: string
  updated_at: string
  verification?: Verification | null
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
  const [investigations, setInvestigations] = useState<Investigation[]>([])
const [proposals, setProposals] = useState<Proposal[]>([])
const [selectedRunId, setSelectedRunId] = useState('')
const [agentRequest, setAgentRequest] = useState(
  'investigate source=external-bot target=prod-secrets',
)
const [proposalDescription, setProposalDescription] = useState(
  'Restrict the selected capability edge to reduce risky reachability.',
)

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

  async function loadWorkflowData(showNotice = false) {
    const [historyResult, proposalResult] = await Promise.all([
      request<{ investigations: Investigation[] }>('/api/workflows/investigations'),
      request<{ proposals: Proposal[] }>('/api/workflows/proposals'),
    ])

    const runs = historyResult.investigations ?? []
    setInvestigations(runs)
    setProposals(proposalResult.proposals ?? [])
    setSelectedRunId(current =>
      current && runs.some(run => run.run_id === current)
        ? current
        : runs[0]?.run_id ?? '',
    )
    if (showNotice) setNotice('Investigation history and proposals refreshed.')
  }

  async function refreshWorkflowData() {
    await runAction('workflow-refresh', async () => {
      await loadWorkflowData(true)
    })
  }

  async function runAgentInvestigation() {
    await runAction('agent', async () => {
      const result = await request<Investigation>('/api/agent/run', {
        method: 'POST',
        body: JSON.stringify({ request: agentRequest }),
      })
      await loadWorkflowData()
      setSelectedRunId(result.run_id)
      setNotice(`Investigation saved. Status: ${result.status}.`)
    })
  }

  async function createProposal() {
    const run = investigations.find(item => item.run_id === selectedRunId)
    if (!run) {
      setError('Select a saved investigation first, or run a new investigation.')
      return
    }
    if (!selectedEdge) {
      setError('Analyze risk and select a candidate edge first.')
      return
    }

    const runSource = run.result?.decision?.arguments?.source ?? source
    const runTarget = run.result?.decision?.arguments?.target ?? target

    await runAction('proposal-create', async () => {
      await request<Proposal>('/api/workflows/proposals', {
        method: 'POST',
        body: JSON.stringify({
          run_id: selectedRunId,
          source: runSource,
          target: runTarget,
          edge_id: selectedEdge,
          description: proposalDescription.trim(),
        }),
      })
      await loadWorkflowData()
      setNotice('Proposal created. Human approval is required before verification.')
    })
  }

  async function decideProposal(proposalId: string, decision: 'approved' | 'rejected') {
    await runAction(`decision-${proposalId}`, async () => {
      await request(`/api/workflows/proposals/${proposalId}/decision`, {
        method: 'POST',
        body: JSON.stringify({ decision }),
      })
      await loadWorkflowData()
      setNotice(`Proposal ${decision}. No infrastructure was changed.`)
    })
  }

  async function verifyProposal(proposalId: string) {
    await runAction(`verify-${proposalId}`, async () => {
      await request(`/api/workflows/proposals/${proposalId}/verify`, {
        method: 'POST',
      })
      await loadWorkflowData()
      setNotice('Simulation verification was saved to the proposal.')
    })
  }

  useEffect(() => {
    void (async () => {
      await checkHealth()
      await runAction('workflow-load', async () => {
        await loadWorkflowData()
      })
    })()
    // Initial connection and workflow load on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
              <span>{node.kind ?? 'entity'} Â· Risk {risk}</span>
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
        <div className="nav-item active">◇ <span>Graph investigation</span></div>
        <div className="nav-item">âŒ˜ <span>Capability paths</span></div>
        <div className="nav-item">â›¨ <span>Safety & verification</span></div>

        <div className="sidebar-bottom">
          <div className="status-line">
            <span className={`status-dot ${health ? 'online' : ''}`} />
            <span>{health ? 'Graph connected' : 'Graph unavailable'}</span>
          </div>
          <span className="muted small">FalkorDB Â· Local workspace</span>
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
          <div className="connection-icon">◇</div>
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
              {busy === 'seed' ? 'Seeding...' : '↻ Seed demo graph'}
            </button>
          </div>

          <div className="query-grid">
            <label>
              <span>STARTING ENTITY</span>
              <input value={source} onChange={e => setSource(e.target.value)} />
            </label>
            <div className="path-arrow">â†’</div>
            <label>
              <span>TARGET ENTITY</span>
              <input value={target} onChange={e => setTarget(e.target.value)} />
            </label>
          </div>

          <div className="action-row">
            <button className="button primary" onClick={discoverPaths} disabled={!!busy || !source.trim() || !target.trim()}>
              {busy === 'paths' ? 'Searching...' : '⌕ Discover paths'}
            </button>
            <button className="button secondary" onClick={analyzePaths} disabled={!!busy || !source.trim() || !target.trim()}>
              {busy === 'analyze' ? 'Analyzing...' : '◇ Analyze risk'}
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
                {analysis.minimum_cost_cut && (
                  <div className="minimum-cut-card">
                    <div className="eyebrow">RECOMMENDED MINIMUM-COST FIX</div>

                    {analysis.minimum_cost_cut.edges.length > 0 ? (
                      <>
                        {analysis.minimum_cost_cut.edges.map(edge => (
                          <div className="minimum-cut-edge" key={edge.edge_id}>
                            <strong>{edge.edge_id}</strong>
                            <span>{edge.relationship ?? edge.relationship_kind}</span>
                            <small>
                              Remediation cost: {edge.remediation_cost ?? 'Unknown'}
                            </small>
                          </div>
                        ))}

                        <div className="minimum-cut-total">
                          <span>Total remediation cost</span>
                          <strong>{analysis.minimum_cost_cut.total_remediation_cost}</strong>
                        </div>
                      </>
                    ) : (
                      <p>No minimum-cost edge recommendation returned.</p>
                    )}

                    <p className="workflow-help">
                      {analysis.minimum_cost_cut.cost_assumption_used
                        ? 'At least one remediation cost was assumed.'
                        : 'Recommendation uses supplied remediation costs.'}
                      {' '}Simulation only; no graph relationships are changed.
                    </p>

                    {analysis.minimum_cost_cut.claim_boundary && (
                      <p className="workflow-help">
                        {analysis.minimum_cost_cut.claim_boundary}
                      </p>
                    )}
                  </div>
                )}

                <label className="edge-picker">
                  <span>SELECT EDGE TO SIMULATE</span>
                  <select
                    value={selectedEdge}
                    onChange={e => setSelectedEdge(e.target.value)}
                  >
                    {analysis.candidate_fixes.map(candidate => (
                      <option key={candidate.edge_id} value={candidate.edge_id}>
                        {candidate.edge_id} Â· blocks {candidate.paths_blocked ?? 0} path(s)
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
                        {candidate.paths_blocked ?? 0} path(s) blocked in simulation Â·{' '}
                        {candidate.remaining_path_count_after_simulated_cut ?? '—'} remaining
                        <br />
                        Remediation cost: {candidate.remediation_cost ?? 'Unknown'}
                      </small>
                    </button>
                  ))}
                </div>

                <button className="button primary full-width" onClick={verifyFix} disabled={!!busy || !selectedEdge}>
                  {busy === 'verify' ? 'Verifying...' : '✓ Verify simulated fix'}
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

        <section className="workflow-center">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">PERSISTENT WORKFLOWS</div>
              <h2>Workflow Center</h2>
            </div>
            <button className="button secondary" onClick={refreshWorkflowData} disabled={!!busy}>
              {busy === 'workflow-refresh' ? 'Refreshing...' : 'Refresh workflows'}
            </button>
          </div>

          <article className="panel workflow-panel">
            <div className="eyebrow">NEW INVESTIGATION</div>
            <h2>Run and save an investigation</h2>
            <p className="workflow-help">
              Example: investigate source=external-bot target=prod-secrets
            </p>
            <label className="workflow-field">
              <span>INVESTIGATION REQUEST</span>
              <input
                value={agentRequest}
                onChange={event => setAgentRequest(event.target.value)}
                maxLength={2000}
                placeholder="investigate source=external-bot target=prod-secrets"
              />
            </label>
            <button className="button primary" onClick={runAgentInvestigation} disabled={!!busy || !agentRequest.trim()}>
              {busy === 'agent' ? 'Running investigation...' : 'Run agent investigation'}
            </button>
          </article>

          <div className="workflow-columns">
            <article className="panel workflow-panel">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">SAVED RUNS</div>
                  <h2>Investigation history</h2>
                </div>
                <span className="pill pill-neutral">{investigations.length} runs</span>
              </div>

              {investigations.length > 0 ? (
                <div className="workflow-list">
                  {investigations.map(run => (
                    <button
                      type="button"
                      key={run.run_id}
                      className={`workflow-item ${selectedRunId === run.run_id ? 'workflow-item-selected' : ''}`}
                      onClick={() => setSelectedRunId(run.run_id)}
                    >
                      <span className="workflow-item-top">
                        <strong>{run.request || 'Untitled investigation'}</strong>
                        <span className="pill pill-neutral">{run.status}</span>
                      </span>
                      <small>{Number.isNaN(Date.parse(run.timestamp)) ? run.timestamp : new Date(run.timestamp).toLocaleString()}</small>
                      <small className="workflow-id">Run: {run.run_id}</small>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <strong>No saved investigations yet</strong>
                  <p>Run an investigation above to populate this history.</p>
                </div>
              )}
            </article>

            <article className="panel workflow-panel">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">HUMAN REVIEW</div>
                  <h2>Remediation proposals</h2>
                </div>
                <span className="pill pill-purple">{proposals.length} proposals</span>
              </div>

              <label className="workflow-field">
                <span>PROPOSAL DESCRIPTION</span>
                <input
                  value={proposalDescription}
                  onChange={event => setProposalDescription(event.target.value)}
                  maxLength={1000}
                />
              </label>
              <button
                className="button primary"
                onClick={createProposal}
                disabled={!!busy || !selectedRunId || !selectedEdge || !proposalDescription.trim()}
              >
                {busy === 'proposal-create' ? 'Creating...' : 'Create proposal from selected edge'}
              </button>
              <p className="workflow-help">
                Selected run: {selectedRunId || 'None'} Â· Selected edge: {selectedEdge || 'Analyze risk first'}
              </p>

              {proposals.length > 0 ? (
                <div className="workflow-list">
                  {proposals.map(proposal => (
                    <div className="workflow-item proposal-item" key={proposal.proposal_id}>
                      <span className="workflow-item-top">
                        <strong>{proposal.edge_id}</strong>
                        <span className={`pill ${proposal.status === 'verified' ? 'pill-green' : proposal.status === 'approved' ? 'pill-purple' : 'pill-neutral'}`}>
                          {proposal.status.toUpperCase()}
                        </span>
                      </span>
                      <p>{proposal.description}</p>
                      <small>{proposal.source} â†’ {proposal.target}</small>
                      <small className="workflow-id">Proposal: {proposal.proposal_id}</small>

                      {proposal.status === 'pending' && (
                        <div className="workflow-actions">
                          <button className="button primary" onClick={() => decideProposal(proposal.proposal_id, 'approved')} disabled={!!busy}>
                            {busy === `decision-${proposal.proposal_id}` ? 'Saving...' : 'Approve'}
                          </button>
                          <button className="button secondary" onClick={() => decideProposal(proposal.proposal_id, 'rejected')} disabled={!!busy}>
                            Reject
                          </button>
                        </div>
                      )}

                      {proposal.status === 'approved' && (
                        <button className="button primary" onClick={() => verifyProposal(proposal.proposal_id)} disabled={!!busy}>
                          {busy === `verify-${proposal.proposal_id}` ? 'Verifying...' : 'Verify in simulation'}
                        </button>
                      )}

                      {proposal.verification && (
                        <div className="verification-summary">
                          <strong>{proposal.verification.verified_in_simulation ? 'No path in simulation' : 'Path remains in simulation'}</strong>
                          <span>
                            Baseline: {proposal.verification.baseline_path_count} Â· Remaining: {proposal.verification.remaining_path_count}
                          </span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <strong>No proposals yet</strong>
                  <p>Analyze risk above, select an edge, and create a proposal.</p>
                </div>
              )}
              <p className="notice">
                Approval records human intent only. Verification excludes an edge during graph search; it does not change production permissions.
              </p>
            </article>
          </div>
        </section>

        <footer className="footer">
          <span>FFlake Â· Graph-native context for AI agents</span>
          <span>Evidence first Â· Human-reviewed actions</span>
        </footer>
      </section>
    </main>
  )
}

export default App

