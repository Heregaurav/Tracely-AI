import { useEffect, useMemo, useState, useRef } from 'react'
import { apiFetch } from '../hooks/useApi'
import { Badge, Empty, Loading } from '../components/shared'
import { ArrowLeft, Cpu, FileText, Mail, Radar, ZoomIn, ZoomOut } from 'lucide-react'
import { graphColor } from '../utils/graph'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { forceSimulation, forceManyBody, forceLink, forceCenter } from 'd3-force-3d'

const TYPE_ICON = { user: Radar, device: Cpu, file: FileText, email: Mail }
const TYPE_LABEL = { user: 'User', device: 'Device', file: 'File', email: 'Email' }

function MetaRow({ label, value }) {
  return (
    <div style={{ display:'flex', justifyContent:'space-between', gap:12, padding:'8px 0', borderBottom:'1px solid rgba(255,255,255,.05)' }}>
      <span style={{ color:'var(--t3)', fontSize:11 }}>{label}</span>
      <span style={{ color:'var(--t2)', fontSize:11, fontFamily:"'JetBrains Mono',monospace", textAlign:'right' }}>{value ?? '—'}</span>
    </div>
  )
}

// draws a small text label as a sprite above each node
function makeLabel(text, color = '#ffffff') {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, 256, 64)
  ctx.font = 'bold 22px Inter, sans-serif'
  ctx.fillStyle = color
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text.length > 18 ? text.slice(0, 16) + '…' : text, 128, 32)
  const tex = new THREE.CanvasTexture(canvas)
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  sprite.scale.set(40, 10, 1)
  return sprite
}

export default function GraphView({ userId, onBack }) {
  const [graphData, setGraphData] = useState(null)
  const [userData, setUserData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [hovered, setHovered] = useState(null)
  const [selected, setSelected] = useState(null)
  const [sceneReady, setSceneReady] = useState(false)
  const mountRef = useRef()
  const sceneRef = useRef()
  const simRef = useRef()

  useEffect(() => {
    if (!userId) return
    let active = true
    Promise.all([
      apiFetch(`/api/graph?user_id=${userId}`),
      apiFetch(`/api/users/${userId}`),
    ])
      .then(([graphPayload, userPayload]) => {
        if (!active) return
        setGraphData(graphPayload)
        setUserData(userPayload)
        const initialNode = graphPayload?.nodes?.find(node => node.type === 'user') || null
        setSelected(initialNode)
      })
      .catch(console.error)
      .finally(() => { if (active) setLoading(false) })

    return () => { active = false }
  }, [userId])

  const nodes = useMemo(() => (graphData?.nodes || []).map(n => ({ ...n })), [graphData])
  const activeNode = selected || hovered || nodes.find(node => node.type === 'user') || null
  const name = userData?.ldap?.name || userData?.name || userId
  const tier = userData?.risk_tier || 'NORMAL'

  // ── Zoom helpers ──────────────────────────────────────────────────────────
  const handleZoom = (direction) => {
    const sref = sceneRef.current
    if (!sref) return
    const { camera } = sref
    const factor = direction === 'in' ? 0.8 : 1.25
    camera.position.multiplyScalar(factor)
  }

  // ── Effect 1: Init Three.js scene ─────────────────────────────────────────
  useEffect(() => {
    if (loading) return
    if (!nodes.length) return
    const mount = mountRef.current
    if (!mount) return

    const width = mount.clientWidth || 800
    const height = mount.clientHeight || 560

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(60, width / height, 1, 10000)
    camera.position.set(0, 0, 800)

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000, 0)
    mount.appendChild(renderer.domElement)

    const ambient = new THREE.AmbientLight(0xffffff, 1.5)
    const dir = new THREE.DirectionalLight(0xffffff, 2.0)
    dir.position.set(0, 200, 300)
    scene.add(ambient, dir)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.07

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()

    sceneRef.current = {
      scene, camera, renderer, controls,
      raycaster, pointer,
      nodeMeshes: new Map(),
      linkObjs: [],
      labelSprites: []
    }

    let rafId = null
    const animate = () => {
      controls.update()
      renderer.render(scene, camera)
      rafId = requestAnimationFrame(animate)
    }
    animate()

    const onResize = () => {
      const w = mount.clientWidth || 800
      const h = mount.clientHeight || 560
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    const handlePointer = (e) => {
      if (!sceneRef.current) return
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const meshes = Array.from(sceneRef.current.nodeMeshes.values())
      const intersects = raycaster.intersectObjects(meshes)
      setHovered(intersects.length ? intersects[0].object.userData.node : null)
    }

    const handleClick = (e) => {
      if (!sceneRef.current) return
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const meshes = Array.from(sceneRef.current.nodeMeshes.values())
      const intersects = raycaster.intersectObjects(meshes)
      if (intersects.length) setSelected(intersects[0].object.userData.node)
    }

    renderer.domElement.addEventListener('pointermove', handlePointer)
    renderer.domElement.addEventListener('click', handleClick)

    setSceneReady(true)

    return () => {
      setSceneReady(false)
      cancelAnimationFrame(rafId)
      renderer.domElement.removeEventListener('pointermove', handlePointer)
      renderer.domElement.removeEventListener('click', handleClick)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      scene.traverse(o => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) {
          if (Array.isArray(o.material)) o.material.forEach(m => m.dispose())
          else o.material.dispose()
        }
      })
      renderer.dispose()
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement)
      sceneRef.current = null
    }
  }, [loading, nodes.length])

  // ── Effect 2: Build graph objects ─────────────────────────────────────────
  useEffect(() => {
    if (!sceneReady || !graphData) return
    const sref = sceneRef.current
    if (!sref) return

    // Cleanup previous meshes
    sref.nodeMeshes.forEach(m => {
      sref.scene.remove(m)
      if (m.geometry) m.geometry.dispose()
      if (m.material) m.material.dispose()
    })
    sref.nodeMeshes.clear()

    // Cleanup previous links
    sref.linkObjs.forEach(l => {
      sref.scene.remove(l.line)
      if (l.line.geometry) l.line.geometry.dispose()
      if (l.line.material) l.line.material.dispose()
    })
    sref.linkObjs.length = 0

    // Cleanup previous labels
    sref.labelSprites.forEach(s => {
      sref.scene.remove(s)
      if (s.material.map) s.material.map.dispose()
      s.material.dispose()
    })
    sref.labelSprites.length = 0

    if (simRef.current) { simRef.current.stop(); simRef.current = null }

    // Create node meshes + labels
    graphData.nodes.forEach(n => {
      const color = new THREE.Color(
        n.activity_score >= 70 ? 0xff6b6b :
        n.activity_score >= 40 ? 0xffd166 : 0x7bd389
      )
      const radius = n.type === 'user' ? 12 : 7
      const geom = new THREE.SphereGeometry(radius, 16, 16)
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.1 })
      const mesh = new THREE.Mesh(geom, mat)
      const px = n.x || (Math.random() * 200 - 100)
      const py = n.y || (Math.random() * 200 - 100)
      const pz = n.z || (Math.random() * 200 - 100)
      mesh.position.set(px, py, pz)
      mesh.userData.node = n
      sref.scene.add(mesh)
      sref.nodeMeshes.set(n.id, mesh)

      // label — sit just above the sphere
      const labelText = n.label || n.key || n.id
      const labelColor = n.type === 'user' ? '#ffffff' : '#aaaaaa'
      const sprite = makeLabel(labelText, labelColor)
      sprite.position.set(px, py + radius + 8, pz)
      sprite.userData.nodeId = n.id
      sref.scene.add(sprite)
      sref.labelSprites.push(sprite)
    })

    // Create link lines
    graphData.edges.forEach(e => {
      const srcMesh = sref.nodeMeshes.get(e.source)
      const tgtMesh = sref.nodeMeshes.get(e.target)
      if (!srcMesh || !tgtMesh) return
      const positions = new Float32Array(6)
      const geom = new THREE.BufferGeometry()
      geom.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      const mat = new THREE.LineBasicMaterial({ color: 0x7f8c8d, transparent: true, opacity: 0.6 })
      const line = new THREE.Line(geom, mat)
      sref.scene.add(line)
      sref.linkObjs.push({ line, source: e.source, target: e.target })
    })

    // Build simulation
    const simNodes = graphData.nodes.map(n => ({
      id: n.id,
      x: n.x || (Math.random() - 0.5) * 200,
      y: n.y || (Math.random() - 0.5) * 200,
      z: n.z || (Math.random() - 0.5) * 200,
    }))

    const nodeById = new Map(simNodes.map(n => [n.id, n]))
    const simLinks = graphData.edges
      .map(e => ({
        source: nodeById.get(e.source),
        target: nodeById.get(e.target),
        value: e.weight || 1,
      }))
      .filter(l => l.source && l.target)

    const sim = forceSimulation(simNodes)
      .force('charge', forceManyBody().strength(-80))
      .force('link', forceLink(simLinks).distance(80).strength(0.2))
      .force('center', forceCenter(0, 0, 0))
      .alphaDecay(0.02)

    sim.on('tick', () => {
      simNodes.forEach(n => {
        const m = sref.nodeMeshes.get(n.id)
        if (m) {
          m.position.set(n.x || 0, n.y || 0, n.z || 0)
          // keep label above its node
          const radius = m.geometry.parameters.radius || 7
          const sprite = sref.labelSprites.find(s => s.userData.nodeId === n.id)
          if (sprite) sprite.position.set(n.x || 0, (n.y || 0) + radius + 8, n.z || 0)
        }
      })
      sref.linkObjs.forEach(l => {
        const src = sref.nodeMeshes.get(l.source)
        const tgt = sref.nodeMeshes.get(l.target)
        if (!src || !tgt) return
        const pos = l.line.geometry.attributes.position.array
        pos[0] = src.position.x; pos[1] = src.position.y; pos[2] = src.position.z
        pos[3] = tgt.position.x; pos[4] = tgt.position.y; pos[5] = tgt.position.z
        l.line.geometry.attributes.position.needsUpdate = true
      })
    })

    simRef.current = sim

    return () => {
      if (simRef.current) { simRef.current.stop(); simRef.current = null }
    }
  }, [graphData, sceneReady])

  return (
    <div className="page">
      <div className="hero" style={{ marginBottom: 20 }}>
        <div>
          <div className="hero-kicker">Graph-Based Threat Detection</div>
          <h1 className="hero-title">Relationship map for {name}</h1>
          <p className="hero-copy">
            High graph score indicates unusual connections across devices, files, or emails.
          </p>
          <div style={{ display:'flex', gap:10, alignItems:'center', flexWrap:'wrap', marginTop:14 }}>
            <button className="btn" onClick={onBack}><ArrowLeft size={14} /> Back to Users</button>
            <Badge tier={tier} />
            <span className="hero-chip">Graph score {graphData?.graph_score?.toFixed?.(1) ?? '0.0'}</span>
            <span className="hero-chip">{graphData?.graph_connections_count || 0} direct connections</span>
          </div>
        </div>
      </div>

      {loading ? <Loading text="Rendering user graph…" /> : !nodes.length ? (
        <Empty text="No graph data available for this user" />
      ) : (
        <div style={{ display:'grid', gridTemplateColumns:'1.45fr .75fr', gap:18 }}>
          <div className="card">
            <div className="card-h">
              <span className="card-t">Interaction Graph</span>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <span className="hero-chip">3D (WebGL) view · hover for details · click to inspect</span>
                {/* ── Zoom buttons ── */}
                <button
                  onClick={() => handleZoom('in')}
                  title="Zoom in"
                  style={{
                    display:'flex', alignItems:'center', justifyContent:'center',
                    width:28, height:28, borderRadius:6, border:'1px solid rgba(255,255,255,.15)',
                    background:'rgba(255,255,255,.06)', color:'var(--t2)',
                    cursor:'pointer', flexShrink:0
                  }}
                ><ZoomIn size={14} /></button>
                <button
                  onClick={() => handleZoom('out')}
                  title="Zoom out"
                  style={{
                    display:'flex', alignItems:'center', justifyContent:'center',
                    width:28, height:28, borderRadius:6, border:'1px solid rgba(255,255,255,.15)',
                    background:'rgba(255,255,255,.06)', color:'var(--t2)',
                    cursor:'pointer', flexShrink:0
                  }}
                ><ZoomOut size={14} /></button>
              </div>
            </div>
            <div className="card-b" style={{ padding: 8 }}>
              <div ref={mountRef} style={{ width: '100%', height: 560 }} className="scene-container" />
            </div>
          </div>

          <div style={{ display:'grid', gap:16, alignContent:'start' }}>
            <div className="card">
              <div className="card-h"><span className="card-t">Selected Node</span></div>
              <div className="card-b">
                {!activeNode ? (
                  <div style={{ color:'var(--t3)', fontSize:12 }}>Hover or click a node to inspect it.</div>
                ) : (
                  <>
                    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:12, marginBottom:12 }}>
                      <div>
                        <div style={{ color:'var(--t1)', fontSize:15, fontWeight:600 }}>{activeNode.label || activeNode.key || activeNode.id}</div>
                        <div style={{ color:'var(--t3)', fontSize:11, fontFamily:"'JetBrains Mono',monospace", marginTop:4 }}>
                          {TYPE_LABEL[activeNode.type] || activeNode.type}
                        </div>
                      </div>
                      <span className="hero-chip" style={{ color: graphColor(activeNode.activity_score), borderColor:`${graphColor(activeNode.activity_score)}55` }}>
                        {activeNode.activity_score?.toFixed?.(1) ?? '0.0'}
                      </span>
                    </div>
                    <MetaRow label="Connections" value={activeNode.connections} />
                    <MetaRow label="Activity Score" value={activeNode.activity_score?.toFixed?.(1)} />
                    <MetaRow label="Graph Score" value={activeNode.metadata?.graph_score?.toFixed?.(1)} />
                    <MetaRow label="Centrality" value={activeNode.metadata?.centrality?.toFixed?.(1)} />
                    <MetaRow label="Weight" value={activeNode.metadata?.interaction_weight?.toFixed?.(1)} />
                  </>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-h"><span className="card-t">Detection Summary</span></div>
              <div className="card-b">
                <div className="graph-score-panel">
                  <div className="graph-score-head">
                    <span>Graph anomaly score</span>
                    <strong style={{ color: graphColor(graphData?.graph_score) }}>{graphData?.graph_score?.toFixed?.(1) ?? '0.0'}</strong>
                  </div>
                  <div className="graph-progress">
                    <div
                      className="graph-progress-fill"
                      style={{ width:`${Math.min(100, graphData?.graph_score || 0)}%`, background:graphColor(graphData?.graph_score) }}
                    />
                  </div>
                </div>
                <div className="callout" style={{ marginTop: 16 }}>
                  <div className="callout-t">How to Read It</div>
                  <div className="callout-b">
                    Red nodes indicate unusually dense or active relationships. Yellow indicates moderate activity, while green reflects expected behavior.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}