"""在临时 PostgreSQL 上复用真实 HTTP 业务验收，包含迁移回退和并发确认。"""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path.cwd()))
from app.main import create_app
from app.core.config import Settings

sys.path.insert(0, str(Path("tests").resolve()))
from test_creative_flow import login, create_project, test_full_flow_and_exactly_once_acceptance, test_concurrent_same_confirmation, test_wedding_requires_both_subjects
from test_m1_runtime import test_recover_after_restart_exactly_once, test_query_exception_and_concurrent_lease, test_m1_migration_backfills_existing_attempts, test_concurrent_admission_and_shared_account_gate
from test_model_settings import test_concurrent_model_publication_one_wins, test_two_instances_refresh_and_keep_old_versions
from test_agent import test_agent_concurrent_idempotency_and_serial_admission, test_agent_cancel_inflight_does_not_publish_late_reply, test_agent_revision_and_privacy_barrier
from test_agent_memory_tools import test_memory_concurrent_confirm_and_stale_send, test_memory_migration_preserves_old_agent_turns, test_read_tools_use_real_quota_job_states_and_safe_failure_reasons, test_tools_database_readonly_and_pool_reset
from test_conversation_events import test_stream_completion_between_ready_and_snapshot, test_stream_memory_and_project_changes_are_invalidations
from test_agent_streaming import test_worker_preview_commits_atomically_and_sse_restores, test_worker_stream_cannot_publish_after_barrier, test_stream_migration_preserves_final_messages
from test_brief_history import test_brief_concurrent_confirm_and_running_change, test_history_paging_is_stable_under_new_messages_and_is_scoped, test_history_tool_respects_forgetting_and_returns_real_sources, test_brief_privacy_cleanup_and_migration_roundtrip

from test_m2_completion import test_knowledge_publish_search_citation_and_revocation, test_knowledge_fake_citation_and_late_unpublish_cannot_commit, test_handoff_cancels_late_reply_staff_messages_and_release_no_replay, test_support_ownership_and_project_privacy_scrubs_staff_text, test_steps_record_bounded_attempts_and_release_is_frozen, test_staff_role_permissions_and_concurrent_claim, test_knowledge_import_idempotency_stale_and_failure_preserves_old

from test_m25 import test_draft_concurrent_edits_preserve_one_winner, test_draft_revision_invalidates_both_confirmation_entries, test_compensation_is_one_review_one_confirmation_no_extra_quota, test_handoff_claim_cancels_inflight_and_owner_exit_denies_staff, test_generic_preferences_retained_only_by_explicit_selection
from test_entitlement_grants import test_grant_key_conflict_and_concurrency, test_grant_transaction_history_and_retry, test_grant_audit_failure_rolls_back_everything
from test_theme_materials import test_publish_request_conflict_and_concurrent_head, test_upload_publish_visible_across_instances_no_restart, test_frozen_confirmation_and_queued_worker_reject_changed_images_or_usage
from test_model_calls import test_admin_only_fixed_twenty_pagination_and_detail_audit, test_actual_agent_run_links_log_to_project, test_concurrent_contexts_and_embedding, test_model_call_migration_refuses_lossy_downgrade
from test_creation_intents import test_real_user_phrase_promotes_selected_style_to_base_no_generation, test_all_mode_switches_remain_reversible_and_do_not_choose_private_assets, test_template_freezes_strict_prompt_roles_and_preserves_low_config


def model_publish_across_instances(client, app):
    """跨 API/Worker 读取相同发布版本，使用虚构凭证但不调用供应商。"""
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as monkeypatch:
        test_two_instances_refresh_and_keep_old_versions(client, app, monkeypatch)


def readonly_tool_database(client, app):
    """在真实 PostgreSQL 验证工具数据库只读和连接归还后写入恢复。"""
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as monkeypatch:
        test_tools_database_readonly_and_pool_reset(client, app, monkeypatch)


def streaming_privacy_barrier(client, app):
    """真实 PostgreSQL 的流式前缀不能跨过隐私代次屏障。"""
    test_worker_stream_cannot_publish_after_barrier(client, app, "privacy")


def concurrent_model_call_contexts(client, app):
    """调用记录短事务与并发范围在PostgreSQL同样隔离。"""
    test_concurrent_contexts_and_embedding(app)


def model_call_migration_guard(client, app):
    """调用证据在PostgreSQL回退时同样受到归档保护。"""
    test_model_call_migration_refuses_lossy_downgrade(app)


def m0_migration_preserves_business_data(client, app):
    """回退新增认证表不应删除原项目，恢复后模式漂移检查须通过。"""
    from app.modules.identity.credentials import provision_admin
    login(client)
    project = create_project(client)
    assert client.get("/ready").status_code == 200
    command.downgrade(Config("alembic.ini"), "cea21ffc2ac6")
    assert client.get("/ready").status_code == 503
    assert client.get(f"/api/v1/web/projects/{project['id']}").status_code == 200
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    with app.state.sessions() as db:
        provision_admin(db, "pgops", "postgres-contract-password", "验收管理员")
        db.commit()
    app.state.settings.admin_auth_mode = "database"
    assert client.post("/api/v1/admin/auth/login", json={"username":"pgops","password":"postgres-contract-password"}).status_code == 200
    assert client.get("/ready").status_code == 200


def main():
    """每个场景迁移新库，避免试用权益与验证码状态互相干扰。"""
    scenarios = [m0_migration_preserves_business_data, test_full_flow_and_exactly_once_acceptance, test_concurrent_same_confirmation, test_wedding_requires_both_subjects, test_recover_after_restart_exactly_once, test_query_exception_and_concurrent_lease, test_m1_migration_backfills_existing_attempts, test_concurrent_admission_and_shared_account_gate, test_concurrent_model_publication_one_wins, model_publish_across_instances]
    scenarios.extend([test_agent_concurrent_idempotency_and_serial_admission, test_agent_cancel_inflight_does_not_publish_late_reply, test_agent_revision_and_privacy_barrier])
    scenarios.extend([test_memory_concurrent_confirm_and_stale_send, test_memory_migration_preserves_old_agent_turns, test_read_tools_use_real_quota_job_states_and_safe_failure_reasons, readonly_tool_database])
    scenarios.extend([test_stream_completion_between_ready_and_snapshot, test_stream_memory_and_project_changes_are_invalidations])
    scenarios.extend([test_worker_preview_commits_atomically_and_sse_restores, streaming_privacy_barrier, test_stream_migration_preserves_final_messages])
    scenarios.extend([test_brief_concurrent_confirm_and_running_change, test_history_paging_is_stable_under_new_messages_and_is_scoped, test_history_tool_respects_forgetting_and_returns_real_sources, test_brief_privacy_cleanup_and_migration_roundtrip])
    scenarios.extend([test_knowledge_publish_search_citation_and_revocation,test_knowledge_fake_citation_and_late_unpublish_cannot_commit,test_handoff_cancels_late_reply_staff_messages_and_release_no_replay,test_support_ownership_and_project_privacy_scrubs_staff_text,test_steps_record_bounded_attempts_and_release_is_frozen,test_staff_role_permissions_and_concurrent_claim,test_knowledge_import_idempotency_stale_and_failure_preserves_old])
    scenarios.extend([test_draft_concurrent_edits_preserve_one_winner, test_draft_revision_invalidates_both_confirmation_entries, test_compensation_is_one_review_one_confirmation_no_extra_quota, test_handoff_claim_cancels_inflight_and_owner_exit_denies_staff, test_generic_preferences_retained_only_by_explicit_selection])
    grant_scenarios = [test_grant_key_conflict_and_concurrency, test_grant_transaction_history_and_retry, test_grant_audit_failure_rolls_back_everything]
    scenarios.extend(grant_scenarios)
    theme_scenarios = [test_publish_request_conflict_and_concurrent_head, test_upload_publish_visible_across_instances_no_restart, test_frozen_confirmation_and_queued_worker_reject_changed_images_or_usage]
    scenarios.extend(theme_scenarios)
    call_scenarios = [test_admin_only_fixed_twenty_pagination_and_detail_audit, test_actual_agent_run_links_log_to_project, concurrent_model_call_contexts, model_call_migration_guard]
    scenarios.extend(call_scenarios)
    intent_scenarios = [test_real_user_phrase_promotes_selected_style_to_base_no_generation, test_all_mode_switches_remain_reversible_and_do_not_choose_private_assets, test_template_freezes_strict_prompt_roles_and_preserves_low_config]
    scenarios.extend(intent_scenarios)
    if "--creation-intents" in sys.argv:
        scenarios = intent_scenarios
    elif "--model-calls" in sys.argv:
        scenarios = call_scenarios
    elif "--entitlements" in sys.argv:
        scenarios = grant_scenarios
    elif "--themes" in sys.argv:
        scenarios = theme_scenarios
    for scenario in scenarios:
        configuration = Config("alembic.ini")
        command.upgrade(configuration, "head")
        with TemporaryDirectory(prefix="yingxu-pg-") as temporary:
            app = create_app(Settings(storage_root=Path(temporary), app_env="test"))
            with TestClient(app) as client:
                scenario(client, app)
            app.state.engine.dispose()
        # 临时验收库归本脚本所有；清理新客服夹具后再执行拒绝有损回退的迁移。
        from sqlalchemy import text
        from app.core.db import make_engine
        cleanup_engine=make_engine(Settings().database_url)
        with cleanup_engine.begin() as connection:
            connection.execute(text("DELETE FROM model_calls"))
            connection.execute(text("UPDATE catalog_heads SET release_id=NULL, revision=0"))
            connection.execute(text("DELETE FROM catalog_releases"))
            connection.execute(text("DELETE FROM catalog_materials"))
            connection.execute(text("DELETE FROM quality_feedback"))
            connection.execute(text("DELETE FROM studio_drafts"))
            connection.execute(text("DELETE FROM model_candidates"))
            connection.execute(text("DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE conversation_id IN (SELECT id FROM conversations WHERE entry_mode='support_only'))"))
            connection.execute(text("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE entry_mode='support_only')"))
            connection.execute(text("DELETE FROM agent_runs WHERE conversation_id IN (SELECT id FROM conversations WHERE entry_mode='support_only')"))
            connection.execute(text("DELETE FROM conversations WHERE entry_mode='support_only'"))
        cleanup_engine.dispose()
        command.downgrade(configuration, "base")
        print("PASS PostgreSQL:", scenario.__name__)
    print(f"PostgreSQL migration roundtrip and {len(scenarios)} business scenarios passed")

if __name__ == "__main__":
    main()
