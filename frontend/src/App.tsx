import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Anchor,
  Button,
  Container,
  Group,
  Select,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import {
  columnFilteringFeature,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  tableFeatures,
  useTable,
  type ColumnDef,
} from '@tanstack/react-table';

import { numberValue, textValue, dataKinds, requestData, requestGames, type DataKind, type Language, type DataResponse, type DisplayRow } from './api';
import type { GameSummary } from './generated/api';

type Translation = {
  siteTitle: string;
  language: string;
  dataCategories: string;
  items: string;
  recipes: string;
  traits: string;
  maps: string;
  search: string;
  searchPlaceholder: string;
  filterPlaceholder: string;
  filterColumn: string;
  sortColumn: string;
  filteredCount: string;
  name: string;
  categories: string;
  level: string;
  value: string;
  ingredients: string;
  days: string;
  cost: string;
  description: string;
  gatheringItems: string;
  monsters: string;
  noData: string;
  noGames: string;
  count: string;
  quantity: string;
  languageNames: Record<Language, string>;
  gameNotFound: string;
};

const translations: Record<Language, Translation> = {
  ja: {
    siteTitle: 'Atelier Tools', language: '言語', dataCategories: 'データ分類', items: 'アイテム', recipes: 'レシピ', traits: '特性', maps: '探索地', search: '検索',
    searchPlaceholder: '一覧を検索', name: '名称', categories: 'カテゴリ', level: 'レベル', value: '価格', ingredients: '材料', days: '日数', cost: 'コスト', description: '説明',
    filterPlaceholder: '絞り込み', filterColumn: '{column}で絞り込み', sortColumn: '{column}で並べ替え',
    filteredCount: '{shown} / {loaded} 件表示',
    gatheringItems: '採取アイテム', monsters: 'モンスター',
    noData: '該当するデータがありません', noGames: '閲覧できるデータがありません', count: '{count} 件', quantity: '{count} 個',
    languageNames: { ja: '日本語', en: '英語', zh: '中国語' }, gameNotFound: 'ゲームが見つかりません',
  },
  en: {
    siteTitle: 'Atelier Tools', language: 'Language', dataCategories: 'Data categories', items: 'Items', recipes: 'Recipes', traits: 'Traits', maps: 'Locations', search: 'Search',
    searchPlaceholder: 'Search table', name: 'Name', categories: 'Categories', level: 'Level', value: 'Price', ingredients: 'Ingredients', days: 'Days', cost: 'Cost', description: 'Description',
    filterPlaceholder: 'Filter', filterColumn: 'Filter {column}', sortColumn: 'Sort by {column}',
    filteredCount: 'Showing {shown} of {loaded} loaded results',
    gatheringItems: 'Gathering items', monsters: 'Monsters',
    noData: 'No matching data', noGames: 'No data is available', count: '{count} results', quantity: 'x{count}',
    languageNames: { ja: 'Japanese', en: 'English', zh: 'Chinese' }, gameNotFound: 'Game not found',
  },
  zh: {
    siteTitle: 'Atelier Tools', language: '语言', dataCategories: '数据分类', items: '道具', recipes: '配方', traits: '特性', maps: '探索地', search: '搜索',
    searchPlaceholder: '搜索列表', name: '名称', categories: '类别', level: '等级', value: '价格', ingredients: '材料', days: '天数', cost: '成本', description: '说明',
    filterPlaceholder: '筛选', filterColumn: '筛选{column}', sortColumn: '按{column}排序',
    filteredCount: '显示 {shown} / {loaded} 项',
    gatheringItems: '采集道具', monsters: '怪物',
    noData: '没有匹配的数据', noGames: '没有可浏览的数据', count: '{count} 项', quantity: '{count} 个',
    languageNames: { ja: '日语', en: '英语', zh: '中文' }, gameNotFound: '找不到游戏',
  },
};

type Game = GameSummary;

const dataTableFeatures = tableFeatures({
  columnFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic },
});
type DataColumn = ColumnDef<typeof dataTableFeatures, DisplayRow>;

function getInitialLanguage(): Language {
  const stored = localStorage.getItem('atelier-tools-language');
  return stored === 'en' || stored === 'zh' ? stored : 'ja';
}

function translate(language: Language, key: keyof Translation, values: Record<string, string> = {}): string {
  let value = translations[language][key];
  if (typeof value !== 'string') return key;
  for (const [name, replacement] of Object.entries(values)) value = value.replace(`{${name}}`, replacement);
  return value;
}

function Header({ language, onLanguageChange }: { language: Language; onLanguageChange: (language: Language) => void }) {
  const languageData = (Object.keys(translations) as Language[]).map((value) => ({ value, label: translations[language].languageNames[value] }));
  return (
    <Group justify="space-between" align="center">
      <Anchor href="/">Atelier Tools</Anchor>
      <Select
        aria-label={translations[language].language}
        label={translations[language].language}
        value={language}
        data={languageData}
        onChange={(value) => { if (value === 'ja' || value === 'en' || value === 'zh') onLanguageChange(value); }}
        allowDeselect={false}
        w={150}
      />
    </Group>
  );
}

function useLanguage(): [Language, (language: Language) => void] {
  const [language, setLanguage] = useState<Language>(getInitialLanguage);
  useEffect(() => {
    localStorage.setItem('atelier-tools-language', language);
    document.documentElement.lang = language;
  }, [language]);
  return [language, setLanguage];
}

function HomePage({ language, onLanguageChange }: { language: Language; onLanguageChange: (language: Language) => void }) {
  const [games, setGames] = useState<Game[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    requestGames(language)
      .then((payload) => setGames(payload.items))
      .catch((reason: Error) => setError(reason.message));
  }, [language]);
  const groups = useMemo(() => {
    const result = new Map<string, Game[]>();
    for (const game of games) result.set(game.series, [...(result.get(game.series) || []), game]);
    return [...result.entries()];
  }, [games]);
  const text = (key: keyof Translation, values?: Record<string, string>) => translate(language, key, values);
  return (
    <Container size="md" py="xl">
      <Stack gap="xl">
        <Header language={language} onLanguageChange={onLanguageChange} />
        <Title order={1}>{text('siteTitle')}</Title>
        {error ? <Text c="red">{error}</Text> : groups.length ? groups.map(([series, seriesGames]) => (
          <Stack key={series} gap="xs">
            <Title order={2}>{series}</Title>
            {seriesGames.map((game) => <Anchor key={game.id} href={`/games/${encodeURIComponent(game.id)}`}>{game.title}</Anchor>)}
          </Stack>
        )) : <Text>{text('noGames')}</Text>}
      </Stack>
    </Container>
  );
}

function DataTable({ data, text }: { data: DataResponse; text: (key: keyof Translation, values?: Record<string, string>) => string }) {
  const columns = useMemo<DataColumn[]>(() => data.columns.map((column) => ({
    id: column.id,
    header: column.label,
    accessorFn: (row) => column.type === 'number' ? numberValue(row, column) : textValue(row, column),
    filterFn: 'includesString',
    sortFn: column.type === 'number' ? 'basic' : 'alphanumeric',
    sortUndefined: 'last',
  })), [data.columns]);
  const table = useTable({ features: dataTableFeatures, data: data.items, columns, getRowId: (item) => String(item.id) });
  const visibleRows = table.getRowModel().rows;
  return <Stack gap="xs" flex={1} mih={0} miw={0}>
    {table.state.columnFilters.length > 0 && <Text size="xs" c="dimmed">{text('filteredCount', { shown: visibleRows.length.toLocaleString(), loaded: data.items.length.toLocaleString() })}</Text>}
    <Table.ScrollContainer minWidth={Math.max(450, columns.length * 180)} maxHeight="100%" type="native" flex={1} mih={0} miw={0}><Table stickyHeader>
    <Table.Thead>
      <Table.Tr>{table.getHeaderGroups()[0].headers.map((header) => <Table.Th key={header.id} aria-sort={header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : 'none'}>
        <Button variant="subtle" size="compact-sm" onClick={header.column.getToggleSortingHandler()} aria-label={text('sortColumn', { column: String(header.column.columnDef.header) })}>
          {String(header.column.columnDef.header)} {header.column.getIsSorted() === 'asc' ? '↑' : header.column.getIsSorted() === 'desc' ? '↓' : '↕'}
        </Button>
      </Table.Th>)}</Table.Tr>
      <Table.Tr>{table.getAllLeafColumns().map((column) => <Table.Th key={column.id}>
        <TextInput size="xs" value={String(column.getFilterValue() ?? '')} onChange={(event) => { const value = event.currentTarget.value; column.setFilterValue(value); }} placeholder={text('filterPlaceholder')} aria-label={text('filterColumn', { column: String(column.columnDef.header) })} />
      </Table.Th>)}</Table.Tr>
    </Table.Thead>
    <Table.Tbody>{visibleRows.length ? visibleRows.map((row) => <Table.Tr key={row.id}>{data.columns.map((column) => <Table.Td key={column.id} style={{ whiteSpace: 'pre-line' }}>{row.original.cells[column.id]?.value ?? ''}</Table.Td>)}</Table.Tr>) : <Table.Tr><Table.Td colSpan={columns.length}>{text('noData')}</Table.Td></Table.Tr>}</Table.Tbody>
    </Table></Table.ScrollContainer>
  </Stack>;
}

function GamePage({ gameId, language, onLanguageChange }: { gameId: string; language: Language; onLanguageChange: (language: Language) => void }) {
  const [kind, setKind] = useState<DataKind>('items');
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [title, setTitle] = useState('');
  const [data, setData] = useState<DataResponse | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    requestGames(language).then((payload) => {
      const game = payload.items.find((item) => item.id === gameId);
      if (!game) throw new Error(translate(language, 'gameNotFound'));
      if (!cancelled) setTitle(game.title);
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [gameId, language]);
  useEffect(() => {
    let cancelled = false;
    setError('');
    setData(null);
    requestData(gameId, kind, language, submittedQuery)
      .then((payload) => { if (!cancelled) setData(payload); })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [gameId, kind, language, submittedQuery]);
  const text = (key: keyof Translation, values?: Record<string, string>) => translate(language, key, values);
  const submit = (event: FormEvent) => { event.preventDefault(); setSubmittedQuery(query); };
  return (
    <Container size="lg" py="xl" h="100dvh" style={{ overflow: 'hidden' }}>
      <Stack gap="lg" h="100%" mih={0}>
        <Header language={language} onLanguageChange={(nextLanguage) => {
          if (nextLanguage !== language) {
            setQuery('');
            setSubmittedQuery('');
            onLanguageChange(nextLanguage);
          }
        }} />
        <Title order={1}>{title}</Title>
        <SegmentedControl
          aria-label={text('dataCategories')}
          value={kind}
          onChange={(value) => {
            if (value === 'items' || value === 'recipes' || value === 'traits' || value === 'maps' || value === 'monsters') {
              setData(null);
              setKind(value);
            }
          }}
          data={dataKinds.map((value) => ({ value, label: value === 'monsters' ? ({ ja: '敵', en: 'Enemies', zh: '敌人' } satisfies Record<Language, string>)[language] : text(value) }))}
          fullWidth
        />
        <form onSubmit={submit}>
          <Group align="end">
            <TextInput value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={text('searchPlaceholder')} aria-label={text('searchPlaceholder')} flex={1} miw={0} />
            <Button type="submit">{text('search')}</Button>
          </Group>
        </form>
        <Text size="sm" c="dimmed">{text('count', { count: (data?.count ?? 0).toLocaleString() })}</Text>
        {error ? <Text c="red">{error}</Text> : data ? <DataTable key={`${kind}-${language}`} data={data} text={text} /> : <Text>{text('noData')}</Text>}
      </Stack>
    </Container>
  );
}

export function App() {
  const [language, setLanguage] = useLanguage();
  const match = window.location.pathname.match(/^\/games\/([^/]+)\/?$/);
  return match ? <GamePage gameId={decodeURIComponent(match[1])} language={language} onLanguageChange={setLanguage} /> : <HomePage language={language} onLanguageChange={setLanguage} />;
}
