import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

export interface Point {
  x: number;
  y: number;
}

interface LayoutNode extends SimulationNodeDatum {
  id: string;
}

const TICKS = 300;

/**
 * Positions nodes with a force simulation run to completion: linked nodes pull
 * together, all nodes repel. React Flow draws the graph but does not lay it out.
 * The result is deterministic for a given input.
 */
export function forceLayout(
  ids: string[],
  links: { source: string; target: string }[],
): Map<string, Point> {
  const nodes: LayoutNode[] = ids.map((id) => ({ id }));
  const known = new Set(ids);
  const edges: SimulationLinkDatum<LayoutNode>[] = links
    .filter((link) => known.has(link.source) && known.has(link.target))
    .map((link) => ({ ...link }));

  const simulation = forceSimulation(nodes)
    .force(
      "link",
      forceLink<LayoutNode, SimulationLinkDatum<LayoutNode>>(edges)
        .id((node) => node.id)
        .distance(180),
    )
    .force("charge", forceManyBody().strength(-700))
    .force("collide", forceCollide(90))
    // A weak pull toward the origin. Unlike a centring force it acts on each node,
    // so files with no dependencies stay near the rest instead of drifting away.
    .force("x", forceX(0).strength(0.08))
    .force("y", forceY(0).strength(0.08))
    .stop();
  simulation.tick(TICKS);

  return new Map(nodes.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
}
