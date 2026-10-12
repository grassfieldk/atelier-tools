import Ajv from 'ajv/dist/2020';
import schema from './generated/api.schema.json';
import type {
  DataResponse,
  DetailResponse,
  GamesResponse,
  DisplayRow,
  Dataset,
  DisplayNumberColumn,
  DisplayTextColumn,
} from './generated/api';

export type { DataResponse, DetailResponse, GamesResponse, DisplayRow };
export type DataKind = DataResponse['kind'];
export type Language = 'ja' | 'en' | 'zh';
export type EntityByKind = Pick<Dataset, DataKind>;
export type EntityFor<Kind extends DataKind> = EntityByKind[Kind][number];
export const dataKinds = [
  'items',
  'recipes',
  'traits',
  'maps',
  'monsters',
] as const satisfies readonly DataKind[];

export function numberValue(row: DisplayRow, column: DisplayNumberColumn): number | undefined {
  const cell = row.cells[column.id];
  if (cell?.type !== 'number') throw new Error(`Invalid numeric cell: ${column.id}`);
  return cell.value ?? undefined;
}

export function textValue(row: DisplayRow, column: DisplayTextColumn): string | undefined {
  const cell = row.cells[column.id];
  if (cell?.type !== 'text') throw new Error(`Invalid text cell: ${column.id}`);
  return cell.value ?? undefined;
}

const ajv = new Ajv({ strict: false });
ajv.addSchema({ ...schema, $id: 'atelier-api' });
const validateGames = ajv.compile<GamesResponse>({ $ref: 'atelier-api#/$defs/GamesResponse' });
const validateData = ajv.compile<DataResponse>({ $ref: 'atelier-api#/$defs/DataResponse' });
const validateDetail = ajv.compile<DetailResponse>({ $ref: 'atelier-api#/$defs/DetailResponse' });

async function fetchJson(path: string): Promise<unknown> {
  const response = await fetch(path);
  const payload: unknown = await response.json();
  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? String(payload.detail)
        : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

export async function requestDetail(
  gameId: string,
  kind: DataKind,
  identifier: number,
  language: Language,
): Promise<DetailResponse> {
  const payload = await fetchJson(
    `/api/games/${encodeURIComponent(gameId)}/data/${kind}/${identifier}?language=${language}`,
  );
  if (
    !validateDetail(payload) ||
    payload.kind !== kind ||
    payload.item.id !== identifier ||
    payload.game.id !== gameId
  )
    throw new Error('Invalid detail response');
  for (const column of payload.columns) {
    if (payload.item.cells[column.id]?.type !== column.type) throw new Error('Invalid detail cell');
  }
  return payload;
}

export async function requestGames(language: Language): Promise<GamesResponse> {
  const payload = await fetchJson(`/api/games?language=${language}`);
  if (!validateGames(payload)) throw new Error('Invalid games response');
  return payload;
}

export async function requestData(
  gameId: string,
  kind: DataKind,
  language: Language,
  query: string,
): Promise<DataResponse> {
  const payload = await fetchJson(
    `/api/games/${encodeURIComponent(gameId)}/data/${kind}?language=${language}&q=${encodeURIComponent(query)}`,
  );
  if (!validateData(payload) || payload.kind !== kind) throw new Error('Invalid data response');
  const identifiers = new Set(payload.columns.map((column) => column.id));
  if (identifiers.size !== payload.columns.length || payload.count !== payload.items.length)
    throw new Error('Invalid table metadata');
  for (const row of payload.items) {
    if (Object.keys(row.cells).length !== identifiers.size) throw new Error('Invalid row columns');
    for (const column of payload.columns) {
      if (row.cells[column.id]?.type !== column.type) throw new Error('Invalid column value type');
    }
  }
  return payload;
}
