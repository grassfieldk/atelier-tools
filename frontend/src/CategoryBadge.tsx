import { useEffect, useState } from 'react';
import { Anchor, Badge, Button, Popover, ScrollArea, Stack, Text } from '@mantine/core';
import { requestData, type DisplayRow, type Language } from './api';
import { LoadingStatus } from './LoadingStatus';

export function CategoryBadge({
  name,
  gameId,
  identifier,
  language,
}: {
  name: string;
  gameId?: string;
  identifier?: number;
  language?: Language;
}) {
  const [opened, setOpened] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    scope: string;
    items?: DisplayRow[];
    error?: string;
  } | null>(null);
  const scope = `${gameId}:${identifier}:${language}:${attempt}`;
  useEffect(() => {
    if (!opened || gameId === undefined || identifier === undefined || language === undefined)
      return;
    let cancelled = false;
    requestData(gameId, 'items', language, '')
      .then((data) => {
        const items = data.items.filter((row) =>
          row.references?.categories?.some(
            (reference) => reference.kind === 'categories' && reference.id === identifier,
          ),
        );
        if (!cancelled) setResult({ scope, items });
      })
      .catch((reason: Error) => {
        if (!cancelled) setResult({ scope, error: reason.message });
      });
    return () => {
      cancelled = true;
    };
  }, [opened, gameId, identifier, language, scope]);
  const label = name.replace(/^[（(](.*)[）)]$/, '$1').trim();
  const style = {
    maxWidth: '100%',
    height: 'auto',
    whiteSpace: 'normal',
    overflowWrap: 'anywhere',
  } as const;
  if (gameId === undefined || identifier === undefined || language === undefined)
    return (
      <Badge variant="light" tt="none" style={style}>
        {label}
      </Badge>
    );
  const current = result?.scope === scope ? result : null;
  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" width={300} withinPortal>
      <Popover.Target>
        <Badge
          component="button"
          type="button"
          variant="light"
          tt="none"
          style={{ ...style, cursor: 'pointer' }}
          aria-expanded={opened}
          aria-haspopup="dialog"
          onClick={() => setOpened((value) => !value)}
        >
          {label}
        </Badge>
      </Popover.Target>
      <Popover.Dropdown>
        {opened && (
          <Stack gap="xs">
            <Text fw={600}>{label}</Text>
            {current?.error ? (
              <>
                <Text c="red" role="alert">
                  {current.error}
                </Text>
                <Button size="xs" variant="subtle" onClick={() => setAttempt((value) => value + 1)}>
                  {
                    ({ ja: '再試行', en: 'Retry', zh: '重试' } satisfies Record<Language, string>)[
                      language
                    ]
                  }
                </Button>
              </>
            ) : !current?.items ? (
              <LoadingStatus language={language} />
            ) : (
              <>
                <Text size="xs" c="dimmed">
                  {
                    {
                      ja: `${current.items.length} 件`,
                      en: `${current.items.length} results`,
                      zh: `${current.items.length} 项`,
                    }[language]
                  }
                </Text>
                <ScrollArea.Autosize mah={300}>
                  <Stack gap="xs">
                    {current.items.length ? (
                      current.items.map((item) => (
                        <Anchor
                          key={item.id}
                          href={`/games/${encodeURIComponent(gameId)}/items/${item.id}`}
                        >
                          {item.cells.name?.value ?? `#${item.id}`}
                        </Anchor>
                      ))
                    ) : (
                      <Text size="sm">
                        {
                          {
                            ja: '該当するデータがありません',
                            en: 'No matching data',
                            zh: '没有匹配的数据',
                          }[language]
                        }
                      </Text>
                    )}
                  </Stack>
                </ScrollArea.Autosize>
              </>
            )}
          </Stack>
        )}
      </Popover.Dropdown>
    </Popover>
  );
}
