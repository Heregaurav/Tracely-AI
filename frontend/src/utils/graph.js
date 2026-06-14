const TYPE_RING = {
  user: 0,
  device: 1,
  file: 2,
  email: 3,
}

const TYPE_ANGLE_OFFSET = {
  user: 0,
  device: -Math.PI / 2,
  file: Math.PI / 6,
  email: Math.PI,
}

export function graphColor(score = 0) {
  if (score >= 70) return 'var(--red)'
  if (score >= 40) return 'var(--yellow)'
  return 'var(--green)'
}

export function layoutGraph(nodes = [], width = 920, height = 560) {
  if (!nodes.length) return new Map()

  const centerX = width / 2
  const centerY = height / 2
  const grouped = nodes.reduce((acc, node) => {
    const type = node.type || 'file'
    if (!acc[type]) acc[type] = []
    acc[type].push(node)
    return acc
  }, {})

  const positions = new Map()
  Object.entries(grouped).forEach(([type, list]) => {
    const ring = TYPE_RING[type] ?? 2
    const radius = ring === 0 ? 0 : 90 + ((ring - 1) * 110)
    list
      .sort((a, b) => (b.activity_score || 0) - (a.activity_score || 0))
      .forEach((node, index) => {
        if (ring === 0) {
          positions.set(node.id, { x: centerX, y: centerY })
          return
        }
        const angle = TYPE_ANGLE_OFFSET[type] + ((Math.PI * 2) / Math.max(list.length, 1)) * index
        const wobble = (index % 2 === 0 ? 1 : -1) * Math.min(18, (node.activity_score || 0) / 6)
        positions.set(node.id, {
          x: centerX + Math.cos(angle) * (radius + wobble),
          y: centerY + Math.sin(angle) * (radius - wobble),
        })
      })
  })

  return positions
}
