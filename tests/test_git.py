import pytest

from conftest import run_git
from gne.core import git


def test_git_line_returns_first_line(git_repo, commit):
    head = commit("feat: first")
    assert git.git_line("rev-parse", "HEAD") == head


def test_git_lines_returns_every_line(git_repo, commit):
    commit("feat: one")
    commit("fix: two")
    assert len(git.git_lines("log", "--pretty=format:%s")) == 2


def test_failure_raises_instead_of_returning_the_error_text(git_repo, commit):
    commit()
    with pytest.raises(git.GitError) as caught:
        git.git_line("rev-parse", "definitely-not-a-ref")
    assert caught.value.returncode != 0


def test_error_text_never_leaks_into_stdout(git_repo, commit):
    """舊實作把 stderr 併進 stdout，錯誤訊息會被當成資料回傳。"""
    commit()
    with pytest.raises(git.GitError) as caught:
        git.git_lines("cat-file", "-t", "definitely-not-a-ref")
    assert caught.value.stderr.strip()


def test_commit_exists_without_string_matching_fatal(git_repo, commit):
    head = commit()
    assert git.commit_exists(head) is True
    assert git.commit_exists("definitely-not-a-ref") is False


def test_commit_exists_is_false_for_a_non_commit_object(git_repo, commit):
    commit()
    tree = git.git_line("rev-parse", "HEAD^{tree}")
    assert git.commit_exists(tree) is False


def test_commit_metadata(git_repo, commit):
    head = commit("fix: 修好了", author="Someone Else <else@example.com>")
    assert git.commit_subject(head) == "fix: 修好了"
    assert git.commit_author(head) == "Someone Else"
    assert git.commit_date(head)


def test_commits_in_range_excludes_merges(git_repo, commit):
    base = commit("feat: base")
    git.git_lines("checkout", "-q", "-b", "side")
    side = commit("feat: on side")
    git.git_lines("checkout", "-q", "master")
    commit("feat: on master")
    git.git_lines("merge", "--no-ff", "-q", "-m", "Merge side", "side")
    found = git.commits_in_range(f"{base}...master")
    subjects = {git.commit_subject(item) for item in found}
    assert side in found
    assert not any(subject.startswith("Merge") for subject in subjects)


# --- 區間：怎麼給的不重要，但要記得上一次那一個 ---


def test_the_range_that_was_given_is_the_range_that_is_used(git_repo, commit):
    commit()
    run_git("tag", "v1", cwd=git_repo)
    commit()
    assert git.resolve_range("v1...HEAD") == "v1...HEAD"


def test_a_given_range_is_remembered_for_next_time(git_repo, commit):
    commit()
    run_git("tag", "v1", cwd=git_repo)
    commit()
    git.resolve_range("v1...HEAD")
    assert git.resolve_range(None) == "v1...HEAD"


def test_the_latest_range_replaces_the_one_before_it(git_repo, commit):
    commit()
    run_git("tag", "v1", cwd=git_repo)
    commit()
    run_git("tag", "v2", cwd=git_repo)
    commit()
    git.resolve_range("v1...HEAD")
    git.resolve_range("v2...HEAD")
    assert git.resolve_range(None) == "v2...HEAD"


def test_the_cache_lives_under_the_git_directory(git_repo, commit):
    """暫存的區間不是專案的宣告：放在 .git 底下，沒有人需要去忽略它。"""
    commit()
    run_git("tag", "v1", cwd=git_repo)
    commit()
    git.resolve_range("v1...HEAD")
    assert git.range_cache_path().is_relative_to(git.git_dir())
    assert not (git_repo / ".gne").exists()


def test_no_range_and_nothing_remembered_is_an_error(git_repo, commit):
    """猜一個基準版本等於猜一個別人 repo 裡沒有的 ref。"""
    commit()
    with pytest.raises(git.RangeNotGiven):
        git.resolve_range(None)


def test_an_empty_cache_counts_as_nothing_remembered(git_repo, commit):
    commit()
    git.remember_range("HEAD...HEAD")
    git.range_cache_path().write_text("  \n\t\n")
    with pytest.raises(git.RangeNotGiven):
        git.resolve_range(None)


def test_outside_a_repository_nothing_is_remembered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert git.remembered_range() is None


def test_current_branch(git_repo, commit):
    commit()
    assert git.current_branch() == "master"


# --- notes 的原始操作 ---


def test_notes_round_trip(git_repo, commit):
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    assert git.notes_show(head) == "type: skip"
    assert git.notes_list() == {head: git.notes_list()[head]}
    git.notes_remove(head)
    assert git.notes_list() == {}


def test_notes_show_raises_when_absent(git_repo, commit):
    head = commit()
    with pytest.raises(git.GitError):
        git.notes_show(head)


# --- 單畫面編輯器需要的 commit 探索 ---


def test_current_user_email(git_repo, commit):
    commit()
    assert git.current_user_email() == "test@example.com"


def test_discover_commits_carries_metadata(git_repo, commit):
    base = commit("feat: base")
    head = commit("fix: 修好了", author="Someone Else <else@example.com>")
    found = git.discover_commits(f"{base}...master")
    assert len(found) == 1
    assert found[0].hash == head
    assert found[0].short_hash == head[:10]
    assert found[0].subject == "fix: 修好了"
    assert found[0].author_email == "else@example.com"
    assert found[0].author == "Someone Else"
    assert found[0].date


def test_discover_commits_separates_origin_from_branch_hash(git_repo, commit):
    """note 掛在原始 hash 上，但看 diff 要用分支上的 hash——原始 commit 可能不在本地。"""
    base = commit("feat: base")
    original = commit("feat: 會被 cherry-pick 的")
    git.git_lines("checkout", "-q", "-b", "side", base)
    git.git_lines("cherry-pick", "-x", original)
    picked = git.git_line("rev-parse", "HEAD")
    found = git.discover_commits(f"{base}...side")
    assert [item.hash for item in found] == [original]
    assert [item.branch_hash for item in found] == [picked]


def test_discover_commits_excludes_merges(git_repo, commit):
    base = commit("feat: base")
    git.git_lines("checkout", "-q", "-b", "side")
    side = commit("feat: on side")
    git.git_lines("checkout", "-q", "master")
    commit("feat: on master")
    git.git_lines("merge", "--no-ff", "-q", "-m", "Merge side", "side")
    found = git.discover_commits(f"{base}...master")
    assert side in [item.hash for item in found]
    assert not any(item.subject.startswith("Merge") for item in found)


def test_discover_commits_costs_one_git_call(git_repo, commit, monkeypatch):
    """舊路徑逐筆呼叫 cherry_picked_origin，commit 一多就是 N 次 git。"""
    base = commit("feat: base")
    for index in range(20):
        commit(f"feat: {index}")
    calls: list[tuple[str, ...]] = []
    original_run = git._run

    def counting_run(*arguments: str, **keywords):
        calls.append(arguments)
        return original_run(*arguments, **keywords)

    monkeypatch.setattr(git, "_run", counting_run)
    found = git.discover_commits(f"{base}...master")
    assert len(found) == 20
    assert len(calls) == 1


def test_discover_commits_survives_control_characters_in_the_body(git_repo, commit):
    """splitlines() 把 \x1c–\x1e 當成換行，記錄分隔不能走行導向的路徑。"""
    base = commit("feat: base")
    (git_repo / "ctl.txt").write_text("x")
    git.git_lines("add", "-A")
    git.git_lines("commit", "-q", "-m", "feat: 標題", "-m", "前\x1e後")
    found = git.discover_commits(f"{base}...master")
    assert [item.subject for item in found] == ["feat: 標題"]


def test_discover_commits_keeps_multi_line_bodies_out_of_the_subject(git_repo, commit):
    base = commit("feat: base")
    (git_repo / "body.txt").write_text("x")
    git.git_lines("add", "-A")
    git.git_lines("commit", "-q", "-m", "feat: 標題", "-m", "第一段\n\n第二段")
    found = git.discover_commits(f"{base}...master")
    assert [item.subject for item in found] == ["feat: 標題"]


# --- commit 詳情畫面的資料來源 ---


def test_commit_files_lists_changed_paths(git_repo, commit):
    head = commit()
    assert git.commit_files(head) == ["file1.txt"]


def test_commit_diff_contains_the_change(git_repo, commit):
    commit("feat: base")
    head = commit()
    assert "file2.txt" in git.commit_diff(head)


def test_commit_diff_works_on_the_root_commit(git_repo, commit):
    """<hash>~1..<hash> 在根 commit 上會失敗，但列表第一筆就可能是它。"""
    head = commit()
    assert "file1.txt" in git.commit_diff(head)


# --- cherry-pick 來源不在這個 repository 裡 ---


def _commit_claiming_origin(git_repo, subject: str, origin: str) -> str:
    (git_repo / f"claim-{subject}.txt").write_text(subject)
    git.git_lines("add", "-A")
    git.git_lines("commit", "-q", "-m", subject, "-m", f"(cherry picked from commit {origin})")
    return git.git_line("rev-parse", "HEAD")


ABSENT = "0123456789abcdef0123456789abcdef01234567"


def test_discover_commits_keeps_the_branch_hash_when_the_origin_is_unknown(git_repo, commit):
    """備註只可能掛在這裡有的物件上；還原成不存在的 hash 會讓後續每個查詢都炸。"""
    base = commit("feat: base")
    head = _commit_claiming_origin(git_repo, "feat: 來自別的 repo", ABSENT)
    found = git.discover_commits(f"{base}...master")
    assert [item.hash for item in found] == [head]
    assert [item.branch_hash for item in found] == [head]


def test_commits_in_range_keeps_the_branch_hash_when_the_origin_is_unknown(git_repo, commit):
    base = commit("feat: base")
    head = _commit_claiming_origin(git_repo, "feat: 來自別的 repo", ABSENT)
    assert git.commits_in_range(f"{base}...master") == [head]


def test_commit_info_keeps_the_branch_hash_when_the_origin_is_unknown(git_repo, commit):
    commit("feat: base")
    head = _commit_claiming_origin(git_repo, "feat: 來自別的 repo", ABSENT)
    assert git.commit_info(head).hash == head


def test_discover_commits_still_unwraps_an_origin_that_is_here(git_repo, commit):
    base = commit("feat: base")
    original = commit("feat: 會被 cherry-pick 的")
    git.git_lines("checkout", "-q", "-b", "side", base)
    git.git_lines("cherry-pick", "-x", original)
    found = git.discover_commits(f"{base}...side")
    assert [item.hash for item in found] == [original]


def test_looking_up_existing_commits_costs_one_call(git_repo, commit, monkeypatch):
    base = commit("feat: base")
    for index in range(10):
        _commit_claiming_origin(git_repo, f"feat: {index}", ABSENT)
    calls: list[tuple[str, ...]] = []
    original_run = git._run

    def counting_run(*arguments: str, **keywords):
        calls.append(arguments)
        return original_run(*arguments, **keywords)

    monkeypatch.setattr(git, "_run", counting_run)
    assert len(git.discover_commits(f"{base}...master")) == 10
    assert len(calls) == 2


# --- 一次取回多筆標題 ---


def test_commit_subjects_returns_a_mapping(git_repo, commit):
    first = commit("feat: 一")
    second = commit("fix: 二")
    assert git.commit_subjects([first, second]) == {first: "feat: 一", second: "fix: 二"}


def test_commit_subjects_omits_objects_that_are_not_here(git_repo, commit):
    head = commit("feat: 一")
    found = git.commit_subjects([head, ABSENT])
    assert found == {head: "feat: 一"}


def test_commit_subjects_of_nothing_is_empty(git_repo, commit):
    commit()
    assert git.commit_subjects([]) == {}


def test_commit_subjects_costs_two_calls(git_repo, commit, monkeypatch):
    revisions = [commit(f"feat: {index}") for index in range(15)]
    calls: list[tuple[str, ...]] = []
    original_run = git._run

    def counting_run(*arguments: str, **keywords):
        calls.append(arguments)
        return original_run(*arguments, **keywords)

    monkeypatch.setattr(git, "_run", counting_run)
    assert len(git.commit_subjects(revisions)) == 15
    assert len(calls) == 2


# --- 與 origin 的差異：照 git 的說法 ---


def test_without_a_tracking_ref_there_is_no_difference_to_report(git_repo, commit):
    commit()
    assert git.notes_sync_state() == (0, 0)


def test_fetching_lands_on_the_tracking_ref_not_on_the_local_one(git_repo, commit, origin):
    """本機有還沒推的備註也一樣取得回來——這正是直接取進 refs/notes/commits 做不到的事。"""
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    local = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)

    second = commit()
    git.notes_add(second, "type: fix", force=False)
    ahead_local = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)

    git.notes_fetch("origin")
    assert run_git("rev-parse", git.NOTES_TRACKING_REF, cwd=git_repo) == local
    assert run_git("rev-parse", git.NOTES_REF, cwd=git_repo) == ahead_local
    assert git.notes_sync_state() == (1, 0)


def test_the_configured_notes_refspec_cannot_clobber_the_local_ref(git_repo, commit, origin):
    """真實 repo 的 remote.origin.fetch 設著 +refs/notes/*:refs/notes/*。

    git 收到命令列 refspec 時仍會依設定順手更新對應的 ref，而那條設定帶著 +，於是取回
    會把本機的備註強制退回 origin 那一版——還沒推的東西就這樣沒了。這條測試釘住它。
    """
    run_git("config", "--add", "remote.origin.fetch", "+refs/notes/*:refs/notes/*", cwd=git_repo)
    shared = commit()
    git.notes_add(shared, "type: skip", force=False)
    git.notes_push("origin")

    mine = commit()
    git.notes_add(mine, "type: fix", force=False)
    before = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)

    git.notes_fetch("origin")
    assert run_git("rev-parse", git.NOTES_REF, cwd=git_repo) == before
    assert git.notes_show(mine) == "type: fix"


def test_being_behind_is_counted_on_the_other_side(git_repo, commit, origin):
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    run_git("update-ref", "-d", git.NOTES_REF, cwd=git_repo)

    git.notes_fetch("origin")
    assert git.notes_sync_state() == (0, 1)
    git.notes_fast_forward()
    assert git.notes_show(head) == "type: skip"


def test_both_sides_having_their_own_is_divergence(git_repo, commit, origin):
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    shared = run_git("rev-parse", git.NOTES_REF, cwd=git_repo)

    second = commit()
    git.notes_add(second, "type: fix", force=False)
    git.notes_push("origin")

    run_git("update-ref", git.NOTES_REF, shared, cwd=git_repo)
    git.notes_add(second, "type: feat", force=True)

    git.notes_fetch("origin")
    assert git.notes_sync_state() == (1, 1)


def test_pushing_sends_the_notes_and_not_the_tracking_ref(git_repo, commit, origin):
    """refs/notes/* 會把 origin/commits 那一份也推上去，那是本機的追蹤資料。"""
    head = commit()
    git.notes_add(head, "type: skip", force=False)
    git.notes_push("origin")
    git.notes_fetch("origin")
    git.notes_push("origin")
    listed = run_git("for-each-ref", "--format=%(refname)", "refs/notes", cwd=origin)
    assert listed == git.NOTES_REF


# --- 備註跟哪個 remote 同步 ---


def test_a_repo_without_remotes_has_no_notes_remote(git_repo, commit):
    """沒有 remote 是一種狀態，不是錯誤：自己記給自己看也是用法。"""
    commit()
    assert git.notes_remote() is None


def test_origin_is_used_when_it_exists(git_repo, commit, origin):
    commit()
    assert git.notes_remote() == "origin"


def test_a_lone_remote_is_used_even_when_it_is_not_called_origin(git_repo, commit, tmp_path):
    commit()
    run_git("remote", "add", "upstream", str(tmp_path / "up.git"), cwd=git_repo)
    assert git.notes_remote() == "upstream"


def test_several_remotes_without_origin_have_to_be_told_apart(git_repo, commit, tmp_path):
    commit()
    run_git("remote", "add", "upstream", str(tmp_path / "up.git"), cwd=git_repo)
    run_git("remote", "add", "fork", str(tmp_path / "fork.git"), cwd=git_repo)
    with pytest.raises(git.RemoteUnclear):
        git.notes_remote()


def test_the_configured_remote_wins_over_origin(git_repo, commit, origin, tmp_path):
    commit()
    run_git("remote", "add", "upstream", str(tmp_path / "up.git"), cwd=git_repo)
    run_git("config", git.REMOTE_CONFIG_KEY, "upstream", cwd=git_repo)
    assert git.notes_remote() == "upstream"


def test_a_configured_remote_that_does_not_exist_is_said_out_loud(git_repo, commit, origin):
    """安靜地退回 origin 會讓人以為推去了別的地方。"""
    commit()
    run_git("config", git.REMOTE_CONFIG_KEY, "nowhere", cwd=git_repo)
    with pytest.raises(git.RemoteUnclear):
        git.notes_remote()


def test_a_range_git_cannot_resolve_is_refused_before_it_is_remembered(git_repo, commit):
    """打錯的區間不該被記起來，下一次沿用時又壞一次。"""
    commit()
    git.resolve_range("HEAD...HEAD")
    with pytest.raises(git.RangeNotGiven):
        git.resolve_range("沒有這個東西...HEAD")
    assert git.remembered_range() == "HEAD...HEAD"
