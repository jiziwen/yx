/** 管理端共用的任务与账户状态名称。 */
export const labels: Record<string, string> = {
  queued: '排队中',
  pending: '已接单',
  submitting: '提交中',
  unknown: '结果未知',
  running: '创作中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  cancel_requested: '取消处理中',
  reconciliation_required: '待核对',
  active: '正常',
  customer: '用户',
  admin: '管理员',
};
