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

type Language = 'ja' | 'en' | 'zh';
type DataKind = 'items' | 'recipes' | 'traits' | 'maps';

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
    searchPlaceholder: '名前で検索', name: '名称', categories: 'カテゴリ', level: 'レベル', value: '価格', ingredients: '材料', days: '日数', cost: 'コスト', description: '説明',
    gatheringItems: '採取アイテム', monsters: 'モンスター',
    noData: '該当するデータがありません', noGames: '閲覧できるデータがありません', count: '{count} 件', quantity: '{count} 個',
    languageNames: { ja: '日本語', en: '英語', zh: '中国語' }, gameNotFound: 'ゲームが見つかりません',
  },
  en: {
    siteTitle: 'Atelier Tools', language: 'Language', dataCategories: 'Data categories', items: 'Items', recipes: 'Recipes', traits: 'Traits', maps: 'Locations', search: 'Search',
    searchPlaceholder: 'Search by name', name: 'Name', categories: 'Categories', level: 'Level', value: 'Price', ingredients: 'Ingredients', days: 'Days', cost: 'Cost', description: 'Description',
    gatheringItems: 'Gathering items', monsters: 'Monsters',
    noData: 'No matching data', noGames: 'No data is available', count: '{count} results', quantity: 'x{count}',
    languageNames: { ja: 'Japanese', en: 'English', zh: 'Chinese' }, gameNotFound: 'Game not found',
  },
  zh: {
    siteTitle: 'Atelier Tools', language: '语言', dataCategories: '数据分类', items: '道具', recipes: '配方', traits: '特性', maps: '探索地', search: '搜索',
    searchPlaceholder: '按名称搜索', name: '名称', categories: '类别', level: '等级', value: '价格', ingredients: '材料', days: '天数', cost: '成本', description: '说明',
    gatheringItems: '采集道具', monsters: '怪物',
    noData: '没有匹配的数据', noGames: '没有可浏览的数据', count: '{count} 项', quantity: '{count} 个',
    languageNames: { ja: '日语', en: '英语', zh: '中文' }, gameNotFound: '找不到游戏',
  },
};

type Game = { id: string; title: string; series: string };
type Item = { id: number; name: string; categories: string | null; level: number | null; value: number | null };
type Ingredient = { name: string | null; reference_id: number; quantity: number };
type Recipe = { id: number; name: string; level: number | null; days: number | null; ingredients: Ingredient[] };
type Trait = { id: number; name: string; cost: number | null; description: string | null };
type NamedReference = { id: number; name: string };
type MapArea = { id: number; name: string; alternate_name: string | null; description: string | null; alternate_description: string | null; items: NamedReference[]; monsters: NamedReference[] };
type DataItem = Item | Recipe | Trait | MapArea;

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

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  const payload = await response.json() as T & { error?: string; detail?: string };
  if (!response.ok) throw new Error(payload.error || payload.detail || `HTTP ${response.status}`);
  return payload;
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
    request<{ items: Game[] }>(`/api/games?language=${language}`)
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

function DataTable({ kind, items, language, text }: { kind: DataKind; items: DataItem[]; language: Language; text: (key: keyof Translation, values?: Record<string, string>) => string }) {
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : language === 'en' ? 'en-US' : 'ja-JP');
  const formatIngredient = (ingredient: Ingredient) => `${ingredient.name || `#${ingredient.reference_id}`} ${text('quantity', { count: numberFormat.format(ingredient.quantity) })}`;
  const formatCategories = (categories: string | null) => categories ? categories.replaceAll('、', language === 'en' ? ', ' : '、') : '';
  if (kind === 'items') {
    return <Table.ScrollContainer minWidth={650} maxHeight="100%" type="native" flex={1} mih={0} miw={0}><Table stickyHeader>
      <Table.Thead><Table.Tr><Table.Th>{text('name')}</Table.Th><Table.Th>{text('categories')}</Table.Th><Table.Th>{text('level')}</Table.Th><Table.Th>{text('value')}</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{(items as Item[]).map((item) => <Table.Tr key={item.id}><Table.Td>{item.name}</Table.Td><Table.Td>{formatCategories(item.categories)}</Table.Td><Table.Td>{item.level ?? ''}</Table.Td><Table.Td>{item.value ?? ''}</Table.Td></Table.Tr>)}</Table.Tbody>
    </Table></Table.ScrollContainer>;
  }
  if (kind === 'recipes') {
    const recipeItems = (items as Recipe[]).filter((item) => Array.isArray(item.ingredients));
    return <Table.ScrollContainer minWidth={760} maxHeight="100%" type="native" flex={1} mih={0} miw={0}><Table stickyHeader>
      <Table.Thead><Table.Tr><Table.Th>{text('name')}</Table.Th><Table.Th>{text('ingredients')}</Table.Th><Table.Th>{text('level')}</Table.Th><Table.Th>{text('days')}</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{recipeItems.map((item) => <Table.Tr key={item.id}><Table.Td>{item.name}</Table.Td><Table.Td>{item.ingredients.map(formatIngredient).join(language === 'en' ? ', ' : '、')}</Table.Td><Table.Td>{item.level ?? ''}</Table.Td><Table.Td>{item.days ?? ''}</Table.Td></Table.Tr>)}</Table.Tbody>
    </Table></Table.ScrollContainer>;
  }
  if (kind === 'maps') {
    const separator = language === 'en' ? ', ' : '、';
    const mapItems = (items as MapArea[]).filter((item) => Array.isArray(item.items) && Array.isArray(item.monsters));
    return <Table.ScrollContainer minWidth={900} maxHeight="100%" type="native" flex={1} mih={0} miw={0}><Table stickyHeader>
      <Table.Thead><Table.Tr><Table.Th>{text('name')}</Table.Th><Table.Th>{text('gatheringItems')}</Table.Th><Table.Th>{text('monsters')}</Table.Th><Table.Th>{text('description')}</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{mapItems.map((item) => <Table.Tr key={item.id}><Table.Td>{item.alternate_name && item.alternate_name !== item.name ? `${item.name} / ${item.alternate_name}` : item.name}</Table.Td><Table.Td>{item.items.map((value) => value.name).join(separator)}</Table.Td><Table.Td>{item.monsters.map((value) => value.name).join(separator)}</Table.Td><Table.Td style={{ whiteSpace: 'pre-line' }}>{item.description || item.alternate_description || ''}</Table.Td></Table.Tr>)}</Table.Tbody>
    </Table></Table.ScrollContainer>;
  }
  return <Table.ScrollContainer minWidth={760} maxHeight="100%" type="native" flex={1} mih={0} miw={0}><Table stickyHeader>
    <Table.Thead><Table.Tr><Table.Th>{text('name')}</Table.Th><Table.Th>{text('cost')}</Table.Th><Table.Th>{text('description')}</Table.Th></Table.Tr></Table.Thead>
    <Table.Tbody>{(items as Trait[]).map((item) => <Table.Tr key={item.id}><Table.Td>{item.name}</Table.Td><Table.Td>{item.cost ?? ''}</Table.Td><Table.Td style={{ whiteSpace: 'pre-line' }}>{item.description || ''}</Table.Td></Table.Tr>)}</Table.Tbody>
  </Table></Table.ScrollContainer>;
}

function GamePage({ gameId, language, onLanguageChange }: { gameId: string; language: Language; onLanguageChange: (language: Language) => void }) {
  const [kind, setKind] = useState<DataKind>('items');
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [title, setTitle] = useState('');
  const [items, setItems] = useState<DataItem[]>([]);
  const [count, setCount] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => { setQuery(''); setSubmittedQuery(''); }, [language]);
  useEffect(() => {
    let cancelled = false;
    request<{ items: Game[] }>(`/api/games?language=${language}`).then((payload) => {
      const game = payload.items.find((item) => item.id === gameId);
      if (!game) throw new Error(translate(language, 'gameNotFound'));
      if (!cancelled) setTitle(game.title);
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [gameId, language]);
  useEffect(() => {
    let cancelled = false;
    setError('');
    setItems([]);
    setCount(0);
    request<{ count: number; items: DataItem[] }>(`/api/games/${encodeURIComponent(gameId)}/data/${kind}?q=${encodeURIComponent(submittedQuery)}&language=${language}&limit=500`)
      .then((payload) => { if (!cancelled) { setItems(payload.items); setCount(payload.count); } })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [gameId, kind, language, submittedQuery]);
  const text = (key: keyof Translation, values?: Record<string, string>) => translate(language, key, values);
  const submit = (event: FormEvent) => { event.preventDefault(); setSubmittedQuery(query); };
  return (
    <Container size="lg" py="xl" h="100dvh" style={{ overflow: 'hidden' }}>
      <Stack gap="lg" h="100%" mih={0}>
        <Header language={language} onLanguageChange={onLanguageChange} />
        <Title order={1}>{title}</Title>
        <SegmentedControl
          aria-label={text('dataCategories')}
          value={kind}
          onChange={(value) => {
            if (value === 'items' || value === 'recipes' || value === 'traits' || value === 'maps') {
              setItems([]);
              setCount(0);
              setKind(value);
            }
          }}
          data={[{ value: 'items', label: text('items') }, { value: 'recipes', label: text('recipes') }, { value: 'traits', label: text('traits') }, { value: 'maps', label: text('maps') }]}
        />
        <form onSubmit={submit}>
          <Group align="end">
            <TextInput value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={text('searchPlaceholder')} aria-label={text('searchPlaceholder')} flex={1} miw={0} />
            <Button type="submit">{text('search')}</Button>
          </Group>
        </form>
        <Text size="sm" c="dimmed">{text('count', { count: count.toLocaleString() })}</Text>
        {error ? <Text c="red">{error}</Text> : items.length ? <DataTable kind={kind} items={items} language={language} text={text} /> : <Text>{text('noData')}</Text>}
      </Stack>
    </Container>
  );
}

export function App() {
  const [language, setLanguage] = useLanguage();
  const match = window.location.pathname.match(/^\/games\/([^/]+)\/?$/);
  return match ? <GamePage gameId={decodeURIComponent(match[1])} language={language} onLanguageChange={setLanguage} /> : <HomePage language={language} onLanguageChange={setLanguage} />;
}
