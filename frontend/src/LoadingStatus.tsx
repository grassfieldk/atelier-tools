import { Group, Loader, Text } from '@mantine/core';
import type { Language } from './api';

export function LoadingStatus({ language }: { language: Language }) {
  return (
    <Group gap="xs" role="status" aria-live="polite">
      <Loader size="sm" />
      <Text size="sm">
        {
          ({ ja: '読み込み中', en: 'Loading', zh: '加载中' } satisfies Record<Language, string>)[
            language
          ]
        }
      </Text>
    </Group>
  );
}
