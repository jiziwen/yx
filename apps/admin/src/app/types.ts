/** 管理端 DTO 的唯一来源为后端 OpenAPI；Row 仅用于表格展示。 */
export type { Inventory } from '@yingxu/api-client';
export type Row = Record<string, unknown>;
