import { useEffect, useRef } from 'react';
import { Anchor, Stack, Title } from '@mantine/core';
import dagre from '@dagrejs/dagre';
import type { DetailResponse, Language } from './api';
import classes from './RecipeTree.module.css';
import { CategoryBadge } from './CategoryBadge';

const labels = {
  ja: {
    title: 'レシピツリー',
    before: '材料として使うレシピ',
    after: 'ここから作れるレシピ',
    empty: '該当するレシピがありません',
    cycle: '循環',
  },
  en: {
    title: 'Recipe tree',
    before: 'Ingredient recipes',
    after: 'Recipes made from this',
    empty: 'No related recipes',
    cycle: 'Cycle',
  },
  zh: {
    title: '配方树',
    before: '材料配方',
    after: '后续配方',
    empty: '没有相关配方',
    cycle: '循环',
  },
};

export function RecipeTree({ data, language }: { data: DetailResponse; language: Language }) {
  const viewport = useRef<HTMLElement>(null);
  const selected = `recipes:${data.item.id}`;
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: 'LR', nodesep: 8, ranksep: 28, marginx: 8, marginy: 8 });
  const tree = data.recipe_tree;
  for (const node of tree?.nodes ?? []) {
    const labelWidth = [...node.name].reduce(
      (total, character) => total + (character.charCodeAt(0) <= 127 ? 10 : 16),
      0,
    );
    const categoryWidth = (node.categories ?? []).reduce(
      (total, category) =>
        total +
        [...category.name.replace(/^[（(](.*)[）)]$/, '$1')].reduce(
          (width, character) => width + (character.charCodeAt(0) <= 127 ? 7 : 12),
          0,
        ) +
        24,
      0,
    );
    graph.setNode(node.key, {
      width: Math.max(72, labelWidth + 24, categoryWidth + 24),
      height: 60,
    });
  }
  for (const edge of tree?.edges ?? []) graph.setEdge(edge.source, edge.target);
  if (tree) dagre.layout(graph);
  const current = graph.hasNode(selected) ? graph.node(selected) : undefined;
  const centerX = current?.x ?? 0;
  useEffect(() => {
    const element = viewport.current;
    if (element) {
      element.scrollLeft = Math.max(0, centerX - element.clientWidth / 2);
    }
  }, [centerX]);
  if (!tree) return null;
  const width = graph.graph().width ?? 240;
  const height = graph.graph().height ?? 96;
  return (
    <Stack gap="sm">
      <Title order={2} size="h4">
        {labels[language].title}
      </Title>
      <section ref={viewport} className={classes.viewport} aria-label={labels[language].title}>
        <div className={classes.map} style={{ width, height }}>
          <svg className={classes.lines} width={width} height={height} aria-hidden="true">
            {tree.edges.map((edge) => {
              const points = graph.edge(edge.source, edge.target).points;
              const first = points[0];
              const last = points[points.length - 1];
              const middleX = (first.x + last.x) / 2;
              const path =
                points.length <= 3 && first.x < last.x
                  ? `M${first.x},${first.y} C${middleX},${first.y} ${middleX},${last.y} ${last.x},${last.y}`
                  : `M${points.map((point: { x: number; y: number }) => `${point.x},${point.y}`).join(' L')}`;
              return (
                <path
                  key={`${edge.source}:${edge.target}`}
                  d={path}
                  className={
                    edge.source === selected || edge.target === selected
                      ? classes.activeLine
                      : undefined
                  }
                />
              );
            })}
          </svg>
          {tree.nodes.map((node) => {
            const position = graph.node(node.key);
            const active = node.key === selected;
            return (
              <div
                key={node.key}
                className={active ? `${classes.node} ${classes.current}` : classes.node}
                style={{
                  left: position.x - position.width / 2,
                  top: position.y - 30,
                  width: position.width,
                }}
              >
                {(node.categories?.length ?? 0) > 0 && (
                  <span className={classes.categories}>
                    {(node.categories ?? []).map((category) => (
                      <CategoryBadge
                        key={category.id}
                        name={category.name}
                        identifier={category.id}
                        gameId={data.game.id}
                        language={language}
                      />
                    ))}
                  </span>
                )}
                <Anchor
                  href={`/games/${encodeURIComponent(data.game.id)}/recipes/${node.id}`}
                  c={active ? 'teal.8' : 'text'}
                  fw={active ? 700 : 500}
                  aria-current={active ? 'page' : undefined}
                >
                  {node.name}
                </Anchor>
              </div>
            );
          })}
        </div>
      </section>
    </Stack>
  );
}
