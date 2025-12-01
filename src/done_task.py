"""既存の CSV プランを読み込み、今日の実績を記入して残りを再計画するユーティリティ

使い方:
 - `python done_task.py` で実行
 - `plans/` 以下の CSV を読み込み、Plan 内の Day 番号を指定して今日とする
 - 今日行った各タスクの実績（完了数）を入力
 - 残りタスクを元に、残りの日数に対する再計画を作成して表示・保存
"""
from typing import List, Dict, Any
import csv
import os
import sys
from datetime import datetime, timedelta
import importlib.util

"""study_plan.py を同ディレクトリのファイルパスから確実にロードする。
通常のモジュール検索に依存せず、スクリプト直実行でも安定して動くようにする。
"""
# 該当ディレクトリにある候補ファイルを順に探す
candidates = ['study_plan.py', 'first_study_plan.py']
module = None
found_path = None
for name in candidates:
    p = os.path.join(os.path.dirname(__file__), name)
    if os.path.exists(p):
        found_path = p
        break

if not found_path:
    raise FileNotFoundError(f"study_plan.py / first_study_plan.py が見つかりません: {os.path.dirname(__file__)}")

spec = importlib.util.spec_from_file_location('study_plan', found_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# 必要な関数を取得（file により名前が異なる場合があるが候補内で互換性を保つ）
allocate_by_priority = getattr(module, 'allocate_by_priority')
prompt_and_save = getattr(module, 'prompt_and_save')
print_plan = getattr(module, 'print_plan')


def load_plan_csv(path: str) -> Dict[str, Any]:
    """CSV（本ツールの出力形式）を読み込み、メタ／日別容量／プラン行を返す。"""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = [r for r in reader]

    i = 0
    meta = {}
    # メタ読み取り（先頭〜空行）
    while i < len(rows) and rows[i]:
        r = rows[i]
        if len(r) >= 2:
            meta[r[0]] = r[1]
        i += 1

    # 空行を飛ばす
    while i < len(rows) and not rows[i]:
        i += 1

    # Day Capacities セクション
    day_capacities = []
    if i < len(rows) and rows[i] and rows[i][0].strip() == 'Day Capacities':
        i += 1  # ヘッダ行
        # 次行は列名 "Day", "AvailableHours"
        i += 1
        while i < len(rows) and rows[i]:
            r = rows[i]
            try:
                day_capacities.append(float(r[1]))
            except Exception:
                pass
            i += 1

    # 空行を飛ばす
    while i < len(rows) and not rows[i]:
        i += 1

    # Plan セクション
    plan_rows = []
    if i < len(rows) and rows[i] and rows[i][0].strip() == 'Plan':
        i += 1  # ヘッダ行
        # 列名行
        i += 1
        while i < len(rows) and rows[i]:
            r = rows[i]
            # 期待: Day, Task, Assigned, Time(hours)
            try:
                day = int(r[0])
            except Exception:
                i += 1
                continue
            name = r[1]
            assigned = 0
            try:
                assigned = int(r[2]) if r[2] != '' else 0
            except Exception:
                assigned = 0
            time_h = 0.0
            try:
                time_h = float(r[3]) if r[3] != '' else 0.0
            except Exception:
                time_h = 0.0

            plan_rows.append({"day": day, "name": name, "assigned": assigned, "time": time_h})
            i += 1

    return {"meta": meta, "day_capacities": day_capacities, "plan_rows": plan_rows}


def aggregate_tasks_from_plan(plan_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Plan 行からタスクごとの合計割当や 1問当たり時間を推定して返す。"""
    tasks = {}
    for r in plan_rows:
        name = r["name"]
        if name == '(休憩/学習無し)':
            continue
        assigned = int(r.get("assigned", 0))
        time_h = float(r.get("time", 0.0))
        if name not in tasks:
            tasks[name] = {"total_assigned": 0, "time_per_item_samples": [], "first_day": r["day"]}
        tasks[name]["total_assigned"] += assigned
        if assigned > 0:
            tasks[name]["time_per_item_samples"].append(time_h / assigned)
        # first_day を最小化
        tasks[name]["first_day"] = min(tasks[name]["first_day"], r["day"])

    # 平均で time_per_item を決定
    for name, info in tasks.items():
        samples = info["time_per_item_samples"]
        time_per_item = (sum(samples) / len(samples)) if samples else 1.0
        info["time_per_item"] = time_per_item
    return tasks


def prompt_float(prompt: str, default: float = None) -> float:
    while True:
        s = input(prompt).strip()
        if s == "" and default is not None:
            return default
        try:
            return float(s)
        except Exception:
            print("数値を入力してください。")


def run():
    plans_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plans'))
    print(f"plans フォルダー: {plans_dir}")
    csv_file = input("読み込む CSV ファイルのパスを入力してください（plans/ 以下なら相対パスで可）: ").strip()
    if csv_file == "":
        print("入力がありません。処理を中止します。")
        return
    if not os.path.isabs(csv_file):
        csv_file = os.path.join(plans_dir, csv_file)

    if not os.path.exists(csv_file):
        print(f"ファイルが見つかりません: {csv_file}")
        return

    data = load_plan_csv(csv_file)
    meta = data["meta"]
    day_capacities = data["day_capacities"]
    plan_rows = data["plan_rows"]
    subject = meta.get("subject", "(無題)")
    # start_date/test_date をメタから取得（ISO 日付文字列 -> datetime.date）
    start_date = None
    test_date = None
    if meta.get("start_date"):
        try:
            start_date = datetime.fromisoformat(meta.get("start_date")).date()
        except Exception:
            start_date = None
    if meta.get("test_date"):
        try:
            test_date = datetime.fromisoformat(meta.get("test_date")).date()
        except Exception:
            test_date = None

    if not day_capacities:
        print("読み込んだ CSV に日別容量情報がありません。続行するには日数と各日の時間を入力してください。")
        nd = int(prompt_float("何日分の計画を作りますか？ (整数): ", 7))
        day_capacities = []
        for i in range(nd):
            h = prompt_float(f"Day {i+1} の利用可能時間 (時間): ", 2.0)
            day_capacities.append(h)

    tasks_info = aggregate_tasks_from_plan(plan_rows)

    # どの日を「今日」とするか
    max_day = max((r["day"] for r in plan_rows), default=len(day_capacities))
    today = input(f"今日とする Day 番号を入力してください (1-{max_day}, デフォルト=1): ").strip()
    if today == "":
        today = 1
    else:
        today = int(today)
    if today < 1:
        today = 1

    # 各タスクについて提案値（その日の割当）を求め、ユーザーに完了数を入力してもらう
    completed_by_task = {}
    for name, info in tasks_info.items():
        total_assigned = info["total_assigned"]
        # prev, today, future assigned
        prev = sum(r["assigned"] for r in plan_rows if r["name"] == name and r["day"] < today)
        today_assigned = sum(r["assigned"] for r in plan_rows if r["name"] == name and r["day"] == today)
        future = sum(r["assigned"] for r in plan_rows if r["name"] == name and r["day"] > today)
        suggested = min(total_assigned - prev, today_assigned)
        if suggested < 0:
            suggested = 0
        s = input(f"{name}: 今日割当={today_assigned}, 過去割当合計={prev}, 合計予定={total_assigned} -> 今日完了数を入力 (デフォルト {suggested}): ").strip()
        if s == "":
            done = int(suggested)
        else:
            try:
                done = int(s)
            except Exception:
                print("整数で入力してください。0 とみなします。")
                done = 0
        # completed can be up to remaining of (total - prev)
        max_possible = max(0, total_assigned - prev)
        if done < 0:
            done = 0
        if done > max_possible:
            print(f"警告: 入力した完了数 {done} は過去含めて残数 {max_possible} を超えています。最大値に切り詰めます。")
            done = max_possible
        completed_by_task[name] = {"done_today": done, "prev_done": prev}

    # 残りタスク数を計算
    remaining_tasks = []
    for name, info in tasks_info.items():
        total_assigned = info["total_assigned"]
        prev = sum(r["assigned"] for r in plan_rows if r["name"] == name and r["day"] < today)
        done_today = completed_by_task.get(name, {}).get("done_today", 0)
        remaining = total_assigned - prev - done_today
        if remaining < 0:
            remaining = 0
        time_per_item = info.get("time_per_item", 1.0)
        first_day = info.get("first_day", today)
        # 優先度は最初に割り当てられた日が早いものを高優先度に
        priority = first_day
        remaining_tasks.append({
            "name": name,
            "remaining": int(remaining),
            "time_per_item": float(time_per_item),
            "difficulty": 1.0,
            "priority": int(priority),
        })

    # 次の日からの day_capacities を取り出す
    total_days = len(day_capacities)
    if today < total_days:
        next_day_caps = day_capacities[today:]
    else:
        print("CSV に残りの計画日がありません。新たに日数を入力してください。")
        nd = int(prompt_float("何日先まで計画しますか？ (整数): ", 7))
        next_day_caps = []
        for i in range(nd):
            h = prompt_float(f"Day {i+1} の利用可能時間 (時間): ", 2.0)
            next_day_caps.append(h)

    # allocate
    # make a deepcopy-like copy so allocate_by_priority can mutate remaining
    tasks_for_alloc = []
    for t in remaining_tasks:
        tasks_for_alloc.append({
            "name": t["name"],
            "remaining": t["remaining"],
            "total": t["remaining"],
            "time_per_item": t["time_per_item"],
            "difficulty": t["difficulty"],
            "priority": t["priority"],
        })

    total_needed = sum(t["remaining"] * t["time_per_item"] * t.get("difficulty", 1.0) for t in tasks_for_alloc)
    plan = allocate_by_priority(next_day_caps, tasks_for_alloc)

    start_day = today + 1

    print('\n=== 再計画結果 ===')
    # Day 表示を元の絶対日付番号に合わせて表示するヘルパー
    def print_plan_with_offset(subject_name, start_day_num, day_caps, tasks_list, total_need, plan_list, base_date=None, test_date=None):
        days = len(day_caps)
        print('\n' + '='*40)
        print(f"科目: {subject_name}")
        print(f"合計利用可能時間: {sum(day_caps):.2f} 時間")
        print(f"必要な総学習時間: {total_need:.2f} 時間")
        print(f"学習日数: {days} (Day {start_day_num} から Day {start_day_num + days - 1} まで)")
        print('='*40 + '\n')

        print("各日の利用可能時間:")
        for i, h in enumerate(day_caps, start=0):
            label = f"Day {start_day_num + i}"
            if base_date is not None:
                day_date = base_date + timedelta(days=(start_day_num + i - 1))
                # 表示を m/d にして、テスト日までの残日数を付記 (Windows では '%-m' が無効なため安全にフォーマット)
                date_str = f"{day_date.month}/{day_date.day}"
                rem = ''
                if test_date is not None:
                    days_left = (test_date - day_date).days
                    rem = f"　テストまで残り{days_left}日"
                label = f"{label} ({date_str}{rem})"
            print(f"  {label}: {h:.2f} 時間")
        print('')

        if total_need <= sum(day_caps):
            print("すべてのタスクを完了するための十分な時間があります。\n")
        else:
            print("注意: 利用可能時間より必要時間が多いです。計画を調整してください。\n")

        for i, day_tasks in enumerate(plan_list, start=0):
            label = f"Day {start_day_num + i}"
            if base_date is not None:
                day_date = base_date + timedelta(days=(start_day_num + i - 1))
                date_str = f"{day_date.month}/{day_date.day}"
                rem = ''
                if test_date is not None:
                    days_left = (test_date - day_date).days
                    rem = f"　テストまで残り{days_left}日"
                label = f"{label} ({date_str}{rem})"
            print(f"{label}:")
            if not day_tasks:
                print("  休憩/学習無し")
            else:
                for it in day_tasks:
                    print(f"  - {it['name']} を {it['assigned']} 問（合計 {it['time']:.2f} 時間）")
            print('')

    print_plan_with_offset(subject + ' (継続)', start_day, next_day_caps, tasks_for_alloc, total_needed, plan, base_date=start_date, test_date=test_date)

    # 保存 (CSV をオフセット付きで保存する)
    save = input("この再計画を保存しますか？ (y/n, デフォルト y): ").strip().lower()
    if save == '' or save == 'y':
        # plans ディレクトリ
        plans_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plans'))
        os.makedirs(plans_dir, exist_ok=True)
        user_name = input("保存するファイル名を入力してください（拡張子なし、Enterで自動生成）: ").strip()
        if user_name == "":
            basename = f"study_plan_{subject}_continued_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            bad = set(list('/\\:*?"<>|'))
            safe = ''.join(ch for ch in user_name if ch not in bad)
            if not safe.lower().endswith('.csv'):
                safe = safe + '.csv'
            basename = safe

        path = os.path.join(plans_dir, basename)
        if os.path.exists(path):
            ans = input(f"{path} は既に存在します。上書きしますか？(y/n): ").strip().lower()
            if ans != 'y':
                print("保存をキャンセルしました。")
                return

        # CSV 書き出し（Day 番号は start_day をオフセットして出力）
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["subject", subject + ' (継続)'])
            writer.writerow(["generated_at", datetime.now().isoformat()])
            writer.writerow(["total_available", f"{sum(next_day_caps):.2f}"])
            writer.writerow(["total_needed", f"{total_needed:.2f}"])
            # 新しい開始日をメタに含める（元 start_date があればそれをオフセット）
            if start_date is not None:
                new_start_date = start_date + timedelta(days=(start_day - 1))
                writer.writerow(["start_date", new_start_date.isoformat()])
            if test_date is not None:
                writer.writerow(["test_date", test_date.isoformat()])
            writer.writerow([])

            writer.writerow(["Day Capacities"])
            writer.writerow(["Day", "AvailableHours"])
            for i, h in enumerate(next_day_caps, start=0):
                writer.writerow([start_day + i, f"{h:.2f}"])
            writer.writerow([])

            writer.writerow(["Plan"])
            writer.writerow(["Day", "Task", "Assigned", "Time(hours)"])
            for i, day_tasks in enumerate(plan, start=0):
                if not day_tasks:
                    writer.writerow([start_day + i, "(休憩/学習無し)", "", ""])
                else:
                    for it in day_tasks:
                        writer.writerow([start_day + i, it["name"], it["assigned"], f"{it['time']:.2f}"])

        print(f"プランを保存しました: {path}")


if __name__ == '__main__':
    run()
