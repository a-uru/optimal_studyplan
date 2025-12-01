"""簡易 GUI (tkinter) - 新規プラン作成と既存 CSV からの更新 (再計画)

使い方:
    python src/plan_gui.py

注意: この GUI は `first_study_plan.py` と `done_task.py` の関数を動的にロードして利用します。
"""
import os
import csv
import importlib.util
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


SRC_DIR = os.path.dirname(__file__)
PLANS_DIR = os.path.abspath(os.path.join(SRC_DIR, '..', 'plans'))
os.makedirs(PLANS_DIR, exist_ok=True)


def load_module(name, filename):
    path = os.path.join(SRC_DIR, filename)
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


first_mod = load_module('first_study_plan', 'first_study_plan.py')
done_mod = load_module('done_task', 'done_task.py')


class PlannerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('学習プラン GUI')
        self.geometry('1000x700')

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True)

        self.frame_new = ttk.Frame(nb)
        self.frame_update = ttk.Frame(nb)
        nb.add(self.frame_new, text='新規プラン')
        nb.add(self.frame_update, text='CSVから更新')

        self._build_new_tab()
        self._build_update_tab()

    def _build_new_tab(self):
        frm = self.frame_new

        left = ttk.Frame(frm)
        right = ttk.Frame(frm)
        left.pack(side='left', fill='y', padx=8, pady=8)
        right.pack(side='left', fill='both', expand=True, padx=8, pady=8)

        # 科目 / 日付 / 共通時間
        ttk.Label(left, text='科目').pack(anchor='w')
        self.entry_subject = ttk.Entry(left)
        self.entry_subject.pack(fill='x')

        ttk.Label(left, text='開始日 (YYYY-MM-DD)').pack(anchor='w')
        self.entry_start = ttk.Entry(left)
        self.entry_start.pack(fill='x')

        ttk.Label(left, text='テスト日 (YYYY-MM-DD、任意)').pack(anchor='w')
        self.entry_test = ttk.Entry(left)
        self.entry_test.pack(fill='x')

        ttk.Label(left, text='1問あたり共通時間 (時間)').pack(anchor='w')
        self.entry_time_per = ttk.Entry(left)
        self.entry_time_per.pack(fill='x')

        ttk.Label(left, text='日ごとの利用可能時間 (カンマ区切り)').pack(anchor='w')
        self.text_day_caps = tk.Text(left, height=4)
        self.text_day_caps.pack(fill='x')

        ttk.Label(left, text='タスク (1行1件: 名前,合計問題数,優先順位,問題コスト)').pack(anchor='w')
        self.text_tasks = tk.Text(left, height=8)
        self.text_tasks.pack(fill='x')

        ttk.Button(left, text='プリセット読み込み', command=self._load_presets).pack(fill='x', pady=4)
        ttk.Button(left, text='プラン生成', command=self._generate_plan).pack(fill='x')
        ttk.Button(left, text='プラン保存 (CSV)', command=self._save_generated_plan).pack(fill='x', pady=4)

        # 右側: プラン出力
        ttk.Label(right, text='プラン出力').pack(anchor='w')
        self.txt_out = scrolledtext.ScrolledText(right)
        self.txt_out.pack(fill='both', expand=True)

        # internal
        self.generated = None
        self.generated_meta = None

    def _load_presets(self):
        if not first_mod:
            messagebox.showerror('エラー', 'first_study_plan.py が見つかりません')
            return
        # populate entries from module presets if available
        try:
            subj = getattr(first_mod, 'SUBJECT_PRESET', '')
            start = getattr(first_mod, 'START_DATE_PRESET', '')
            test = getattr(first_mod, 'TEST_DATE_PRESET', '')
            caps = getattr(first_mod, 'DAY_CAPACITIES_PRESET', [])
            tpi = getattr(first_mod, 'COMMON_TIME_PER_ITEM_PRESET', '')
            tasks = getattr(first_mod, 'TASKS_PRESET', [])
        except Exception:
            messagebox.showwarning('警告', 'プリセット読み込みに失敗しました')
            return
        self.entry_subject.delete(0, 'end'); self.entry_subject.insert(0, str(subj))
        self.entry_start.delete(0, 'end'); self.entry_start.insert(0, str(start) if start else '')
        self.entry_test.delete(0, 'end'); self.entry_test.insert(0, str(test) if test else '')
        self.entry_time_per.delete(0, 'end'); self.entry_time_per.insert(0, str(tpi))
        self.text_day_caps.delete('1.0', 'end'); self.text_day_caps.insert('1.0', ','.join(str(x) for x in caps))
        self.text_tasks.delete('1.0', 'end')
        for t in tasks:
            line = f"{t.get('name')},{t.get('total')},{t.get('priority')},{t.get('difficulty')}\n"
            self.text_tasks.insert('end', line)

    def _parse_inputs(self):
        subject = self.entry_subject.get().strip()
        start_date = self.entry_start.get().strip() or None
        test_date = self.entry_test.get().strip() or None
        try:
            time_per = float(self.entry_time_per.get().strip())
        except Exception:
            time_per = 0.0
        caps_s = self.text_day_caps.get('1.0', 'end').strip()
        day_caps = []
        if caps_s:
            for part in caps_s.replace('\n',',').split(','):
                part = part.strip()
                if not part: continue
                try:
                    day_caps.append(float(part))
                except Exception:
                    pass
        tasks = []
        for line in self.text_tasks.get('1.0','end').splitlines():
            if not line.strip(): continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 4:
                continue
            name, total, priority, difficulty = parts[0], int(parts[1]), int(parts[2]), float(parts[3])
            tasks.append({'name': name, 'remaining': total, 'total': total, 'time_per_item': time_per, 'difficulty': difficulty, 'priority': priority})
        return subject, start_date, test_date, day_caps, tasks

    def _generate_plan(self):
        subject, start_date, test_date, day_caps, tasks = self._parse_inputs()
        if not tasks or not day_caps:
            messagebox.showwarning('警告', '日数とタスクを入力してください')
            return
        # use allocate_by_priority from first_mod if present
        if first_mod and hasattr(first_mod, 'allocate_by_priority'):
            # copy tasks for mutation
            import copy
            tasks_copy = copy.deepcopy(tasks)
            plan = first_mod.allocate_by_priority(day_caps, tasks_copy)
            total_needed = sum(t['total'] * t['time_per_item'] * t.get('difficulty',1.0) for t in tasks)
        else:
            messagebox.showerror('エラー', '割当関数が見つかりません')
            return

        # show
        self.txt_out.delete('1.0','end')
        self.txt_out.insert('end', f"科目: {subject}\n開始: {start_date}\nテスト: {test_date}\n\n")
        # show (original line-by-line per day)
        self.generated = plan
        self.generated_meta = {'subject': subject, 'start_date': start_date, 'test_date': test_date, 'day_caps': day_caps, 'tasks': tasks, 'total_needed': total_needed}
        self.txt_out.delete('1.0','end')
        self.txt_out.insert('end', f"科目: {subject}\n開始: {start_date}\nテスト: {test_date}\n\n")
        for i, day_tasks in enumerate(plan, start=1):
            label = f"Day {i}"
            if start_date:
                try:
                    base = datetime.fromisoformat(start_date).date()
                    day_date = base + timedelta(days=(i-1))
                    label += f" ({day_date.month}/{day_date.day})"
                except Exception:
                    pass
            self.txt_out.insert('end', f"{label}:\n")
            if not day_tasks:
                self.txt_out.insert('end', '  休憩/学習無し\n')
            else:
                for it in day_tasks:
                    self.txt_out.insert('end', f"  - {it['name']} を {it['assigned']} 問 合計 {it['time']:.2f} 時間\n")
            self.txt_out.insert('end','\n')

    def _save_generated_plan(self):
        if not self.generated or not self.generated_meta:
            messagebox.showwarning('警告', '先にプランを生成してください')
            return
        fname = filedialog.asksaveasfilename(initialdir=PLANS_DIR, defaultextension='.csv', filetypes=[('CSVファイル','*.csv')])
        if not fname:
            return
        # write CSV similar to first_study_plan format, include start_date/test_date
        meta = self.generated_meta
        plan = self.generated
        with open(fname, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['subject', meta['subject']])
            writer.writerow(['generated_at', datetime.now().isoformat()])
            writer.writerow(['total_available', f"{sum(meta['day_caps']):.2f}"])
            writer.writerow(['total_needed', f"{meta['total_needed']:.2f}"])
            if meta.get('start_date'):
                writer.writerow(['start_date', meta['start_date']])
            if meta.get('test_date'):
                writer.writerow(['test_date', meta['test_date']])
            writer.writerow([])
            writer.writerow(['Day Capacities'])
            writer.writerow(['Day','AvailableHours'])
            for i,h in enumerate(meta['day_caps'], start=1):
                writer.writerow([i, f"{h:.2f}"])
            writer.writerow([])
            writer.writerow(['Plan'])
            writer.writerow(['Day','Task','Assigned','Time(hours)'])
            for i, day_tasks in enumerate(plan, start=1):
                if not day_tasks:
                    writer.writerow([i, '(休憩/学習無し)','', ''])
                else:
                    for it in day_tasks:
                        writer.writerow([i, it['name'], it['assigned'], f"{it['time']:.2f}"])
        messagebox.showinfo('保存完了', f'プランを保存しました: {fname}')

    # -- update tab
    def _build_update_tab(self):
        frm = self.frame_update
        top = ttk.Frame(frm)
        top.pack(fill='x', padx=8, pady=8)
        ttk.Button(top, text='CSV読み込み', command=self._load_csv_for_update).pack(side='left')
        ttk.Label(top, text='今日 (Day#)').pack(side='left', padx=6)
        self.entry_today = ttk.Entry(top, width=6)
        self.entry_today.pack(side='left')
        ttk.Button(top, text='今日を適用して再計画', command=self._apply_today_replan).pack(side='left', padx=6)

        self.txt_update = scrolledtext.ScrolledText(frm)
        self.txt_update.pack(fill='both', expand=True, padx=8, pady=8)
        # internal
        self.loaded_meta = None
        self.loaded_plan_rows = None

    def _load_csv_for_update(self):
        fpath = filedialog.askopenfilename(initialdir=PLANS_DIR, filetypes=[('CSVファイル','*.csv')])
        if not fpath:
            return
        # use done_task.load_plan_csv if available
        plan_data = None
        if done_mod and hasattr(done_mod, 'load_plan_csv'):
            plan_data = done_mod.load_plan_csv(fpath)
        else:
            # simple loader
            with open(fpath, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = [r for r in reader]
            # minimal parse: reuse code from done_task (lightweight)
            i=0; meta={}
            while i < len(rows) and rows[i]:
                r=rows[i]
                if len(r)>=2: meta[r[0]]=r[1]
                i+=1
            while i < len(rows) and not rows[i]: i+=1
            day_caps=[]
            if i < len(rows) and rows[i] and rows[i][0].strip()=='Day Capacities':
                i+=2
                while i < len(rows) and rows[i]:
                    try: day_caps.append(float(rows[i][1]))
                    except: pass
                    i+=1
            while i < len(rows) and not rows[i]: i+=1
            plan_rows=[]
            if i < len(rows) and rows[i] and rows[i][0].strip()=='Plan':
                i+=2
                while i < len(rows) and rows[i]:
                    r=rows[i]
                    try: day=int(r[0])
                    except: i+=1; continue
                    name=r[1]; assigned=0
                    try: assigned=int(r[2]) if r[2] else 0
                    except: assigned=0
                    timeh=0.0
                    try: timeh=float(r[3]) if r[3] else 0.0
                    except: timeh=0.0
                    plan_rows.append({'day':day,'name':name,'assigned':assigned,'time':timeh})
                    i+=1
            plan_data={'meta':meta,'day_capacities':day_caps,'plan_rows':plan_rows}

        self.loaded_meta = plan_data['meta']
        self.loaded_plan_rows = plan_data['plan_rows']
        # print summary
        self.txt_update.delete('1.0','end')
        self.txt_update.insert('end', f"読み込み: {os.path.basename(fpath)}\nメタ情報: {self.loaded_meta}\n\n")
        # list tasks
        tasks_info = {}
        for r in self.loaded_plan_rows:
            if r['name']=='(休憩/学習無し)': continue
            if r['name'] not in tasks_info: tasks_info[r['name']]={'total':0,'today':0,'prev':0}
            tasks_info[r['name']]['total'] += r['assigned']
        for name,info in tasks_info.items():
            self.txt_update.insert('end', f"{name}: 合計割当 {info['total']}\n")

    def _apply_today_replan(self):
        if not self.loaded_plan_rows:
            messagebox.showwarning('警告','まずCSVを読み込んでください')
            return
        try:
            today = int(self.entry_today.get().strip() or '1')
        except Exception:
            today = 1
        # aggregate tasks
        tasks = {}
        for r in self.loaded_plan_rows:
            if r['name']=='(休憩/学習無し)': continue
            info = tasks.setdefault(r['name'], {'total_assigned':0, 'time_per_item_samples':[], 'first_day':r['day']})
            info['total_assigned'] += r['assigned']
            if r['assigned']>0:
                info['time_per_item_samples'].append(r['time']/r['assigned'] if r['assigned'] else 0)
            info['first_day'] = min(info['first_day'], r['day'])

        # prompt user for done_today values via simple dialog loop
        done_today = {}
        for name,info in tasks.items():
            prev = sum(r['assigned'] for r in self.loaded_plan_rows if r['name']==name and r['day']<today)
            today_assigned = sum(r['assigned'] for r in self.loaded_plan_rows if r['name']==name and r['day']==today)
            suggested = min(info['total_assigned'] - prev, today_assigned)
            s = tk.simpledialog.askstring('完了数入力', f"{name}: 今日割当={today_assigned}, 過去割当合計={prev}, 合計予定={info['total_assigned']} -> 今日完了数 (デフォルト {suggested}): ")
            if s is None or s.strip()=='' : done = suggested
            else:
                try: done=int(s)
                except: done=0
            done_today[name]=done

        # build remaining tasks
        remaining_tasks=[]
        for name,info in tasks.items():
            prev = sum(r['assigned'] for r in self.loaded_plan_rows if r['name']==name and r['day']<today)
            rem = info['total_assigned'] - prev - done_today.get(name,0)
            if rem < 0: rem = 0
            tpi = (sum(info['time_per_item_samples'])/len(info['time_per_item_samples'])) if info['time_per_item_samples'] else 1.0
            remaining_tasks.append({'name':name,'remaining':int(rem),'time_per_item':float(tpi),'difficulty':1.0,'priority':int(info['first_day'])})

        # next days capacities: ask user
        s = tk.simpledialog.askstring('次の日入力', '次の日の利用可能時間をカンマ区切りで入力してください（例:2,3,2）:')
        if s is None: return
        next_caps = []
        for part in s.split(','):
            try: next_caps.append(float(part.strip()))
            except: pass

        # allocate using first_mod.allocate_by_priority
        tasks_alloc = []
        for t in remaining_tasks:
            tasks_alloc.append({'name':t['name'],'remaining':t['remaining'],'total':t['remaining'],'time_per_item':t['time_per_item'],'difficulty':t['difficulty'],'priority':t['priority']})
        if first_mod and hasattr(first_mod, 'allocate_by_priority'):
            plan = first_mod.allocate_by_priority(next_caps, tasks_alloc)
        else:
            messagebox.showerror('エラー','割当関数が見つかりません')
            return

        # render replan + remaining original future days in calendar view
        try:
            if self.loaded_meta.get('start_date'):
                base_date = datetime.fromisoformat(self.loaded_meta.get('start_date')).date()
                start_day = today + 1
                new_start = (base_date + timedelta(days=(today))).isoformat()
            else:
                new_start = None
                start_day = today + 1
        except Exception:
            new_start = None
            start_day = today + 1

        header_meta = (self.loaded_meta.get('subject','(無題)'), new_start or self.loaded_meta.get('start_date'), self.loaded_meta.get('test_date'))

        # collect future days from loaded_plan_rows where day > cutoff_day and append after replan
        cutoff_day = today + len(next_caps)
        future_days_map = {}
        max_future_day = cutoff_day
        for r in self.loaded_plan_rows:
            try:
                d = int(r.get('day', 0))
            except Exception:
                continue
            if d > cutoff_day:
                max_future_day = max(max_future_day, d)
                future_days_map.setdefault(d, []).append({'name': r.get('name'), 'assigned': int(r.get('assigned',0)), 'time': float(r.get('time',0.0))})

        future_plan = []
        if future_days_map:
            for daynum in range(cutoff_day+1, max_future_day+1):
                day_tasks = future_days_map.get(daynum, [])
                filtered = [t for t in day_tasks if t.get('name') and t.get('name') != '(休憩/学習無し)']
                if filtered:
                    conv = [{'name': t['name'], 'assigned': t['assigned'], 'time': t['time']} for t in filtered]
                else:
                    conv = []
                future_plan.append(conv)

        combined_plan = []
        combined_plan.extend(plan)
        if future_plan:
            combined_plan.extend(future_plan)

        # print combined plan in original (per-day) format
        self.txt_update.delete('1.0','end')
        self.txt_update.insert('end', f"再計画（開始 Day {start_day}）:\n\n")
        # base date for label calculation
        base_for_print = None
        if new_start:
            try:
                base_for_print = datetime.fromisoformat(new_start).date()
            except Exception:
                base_for_print = None
        for idx, day_tasks in enumerate(combined_plan, start=start_day):
            label = f"Day {idx}"
            if base_for_print:
                try:
                    d = base_for_print + timedelta(days=(idx - start_day))
                    label += f" ({d.month}/{d.day})"
                except Exception:
                    pass
            self.txt_update.insert('end', f"{label}:\n")
            if not day_tasks:
                self.txt_update.insert('end','  休憩/学習無し\n')
            else:
                for it in day_tasks:
                    self.txt_update.insert('end', f"  - {it['name']} を {it['assigned']} 問 合計 {it['time']:.2f} 時間\n")
            self.txt_update.insert('end','\n')

        # ask to save
        if messagebox.askyesno('保存確認','この再計画を保存しますか？'):
            fname = filedialog.asksaveasfilename(initialdir=PLANS_DIR, defaultextension='.csv', filetypes=[('CSVファイル','*.csv')])
            if fname:
                with open(fname,'w',newline='',encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(['subject', self.loaded_meta.get('subject','(無題)')])
                    w.writerow(['generated_at', datetime.now().isoformat()])
                    w.writerow(['total_available', f"{sum(next_caps):.2f}"])
                    total_needed = sum(t['remaining']*t['time_per_item'] for t in remaining_tasks)
                    w.writerow(['total_needed', f"{total_needed:.2f}"])
                    # start_date for replan
                    try:
                        if self.loaded_meta.get('start_date'):
                            new_start = datetime.fromisoformat(self.loaded_meta.get('start_date')).date() + timedelta(days=(today))
                            w.writerow(['start_date', new_start.isoformat()])
                    except Exception:
                        pass
                    if self.loaded_meta.get('test_date'):
                        w.writerow(['test_date', self.loaded_meta.get('test_date')])
                    w.writerow([])
                    w.writerow(['Day Capacities'])
                    w.writerow(['Day','AvailableHours'])
                    for i,h in enumerate(next_caps, start= start_day):
                        w.writerow([i, f"{h:.2f}"])
                    w.writerow([])
                    w.writerow(['Plan'])
                    w.writerow(['Day','Task','Assigned','Time(hours)'])
                    for i, day_tasks in enumerate(plan, start=start_day):
                        if not day_tasks:
                            w.writerow([i,'(休憩/学習無し)','',''])
                        else:
                            for it in day_tasks:
                                w.writerow([i,it['name'],it['assigned'],f"{it['time']:.2f}"])
                messagebox.showinfo('保存完了', f'プランを保存しました: {fname}')


if __name__ == '__main__':
    app = PlannerGUI()
    app.mainloop()
