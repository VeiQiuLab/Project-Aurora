"""Local OneBot group archive. No owner Memory, credentials, media or AI writes.

Authorization and raw records commit together in SQLite, independently of reply
admission. No TTL, pruning, summary substitution or startup deletion exists.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import time

from modules.memory_retrieval import _tokens


class ArchiveError(RuntimeError):
    def __init__(self, code='QQ_ARCHIVE_FAILED'):
        super().__init__(code)
        self.code = code


class GroupArchive:
    def __init__(self, path):
        self.path = Path(path)

    def pending_recalls(self):
        # Operational intent, no message body. One owned Sidecar event loop is
        # the writer; crash recovery replays intent before exposing archive rows.
        file=self.path.with_suffix('.privacy.json')
        if not file.exists():return []
        try:
            rows=json.loads(file.read_text(encoding='utf-8'))
            if not isinstance(rows,list):raise ValueError()
            for r in rows:
                if (not isinstance(r,dict) or set(r)!={'post_type','notice_type','self_id','group_id','message_id'}
                        or r['post_type']!='notice' or r['notice_type']!='group_recall'
                        or any(type(r[k]) is not int or not 0<r[k]<2**63 for k in ('self_id','group_id'))
                        or type(r['message_id']) is not int or not -(2**63)<r['message_id']<2**63):raise ValueError()
            return rows
        except (OSError,ValueError,UnicodeError):raise ArchiveError() from None

    def save_recalls(self, rows):
        file=self.path.with_suffix('.privacy.json')
        partial=file.with_name(file.name+'.'+secrets.token_hex(8)+'.partial')
        try:
            file.parent.mkdir(parents=True,exist_ok=True)
            with partial.open('x',encoding='utf-8') as out:
                json.dump(rows,out);out.flush();os.fsync(out.fileno())
            os.replace(partial,file)
        except (OSError,ValueError,UnicodeError):raise ArchiveError() from None

    def remember_recall(self, event):
        row={'post_type':'notice','notice_type':'group_recall',
             **{k:event[k] for k in ('self_id','group_id','message_id')}}
        rows=self.pending_recalls()
        if row not in rows:rows.append(row);self.save_recalls(rows)

    def finish_recall(self, event):
        rows=self.pending_recalls()
        key=tuple(event[k] for k in ('self_id','group_id','message_id'))
        remaining=[r for r in rows if tuple(r[k] for k in ('self_id','group_id','message_id'))!=key]
        if remaining!=rows:self.save_recalls(remaining)

    @contextmanager
    def database(self, *, write=False):
        db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=2)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA secure_delete=ON')
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS groups (
                    account_id TEXT NOT NULL, group_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    authorized_at INTEGER NOT NULL,
                    PRIMARY KEY(account_id, group_id));
                CREATE TABLE IF NOT EXISTS messages (
                    key TEXT PRIMARY KEY, platform TEXT NOT NULL,
                    account_id TEXT NOT NULL, group_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL, display_name TEXT NOT NULL,
                    message_id TEXT NOT NULL, timestamp INTEGER NOT NULL,
                    message_type TEXT NOT NULL, text TEXT NOT NULL,
                    segments TEXT NOT NULL, ingested_at INTEGER NOT NULL,
                    UNIQUE(account_id, group_id, message_id),
                    FOREIGN KEY(account_id, group_id) REFERENCES groups(account_id, group_id));
                CREATE TABLE IF NOT EXISTS suppressed (key TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS relations (parent_key TEXT NOT NULL,child_key TEXT NOT NULL,
                    PRIMARY KEY(parent_key,child_key));
                CREATE INDEX IF NOT EXISTS archive_group_time ON messages(account_id,group_id,timestamp,key);
                CREATE INDEX IF NOT EXISTS archive_sender_time ON messages(account_id,group_id,sender_id,timestamp,key);
            ''')
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            if write: db.commit()
        except ArchiveError:
            if db: db.rollback()
            raise
        except (sqlite3.Error, OSError, ValueError, UnicodeError):
            if db: db.rollback()
            raise ArchiveError() from None
        finally:
            if db: db.close()

    @staticmethod
    def key(account, group, message):
        return hashlib.sha256(f'onebot11:{account}:group:{group}:{message}'.encode()).hexdigest()

    @staticmethod
    def authorize(db, account, group):
        row = db.execute('SELECT * FROM groups WHERE account_id=? AND group_id=?',(account,group)).fetchone()
        if row is None: raise ArchiveError('QQ_NOT_AUTHORIZED')
        return row

    def configure(self, account, group, enabled):
        with self.database(write=True) as db:
            db.execute('INSERT INTO groups VALUES (?,?,?,0,?) ON CONFLICT(account_id,group_id) '
                       'DO UPDATE SET enabled=excluded.enabled', (account,group,int(enabled),int(time())))

    def policies(self):
        if not self.path.exists(): return []
        with self.database() as db:
            return [dict(r) for r in db.execute('SELECT account_id,group_id,enabled FROM groups ORDER BY account_id,group_id')]

    def ingest(self, account, event, *, reply_to=None):
        """Returns a recalled group ID, never requests generation or sending."""
        if not self.path.exists() or str(event.get('self_id')) != account: return None
        if type(event.get('group_id')) is not int or not 0 < event['group_id'] < 2**63:return None
        group = str(event.get('group_id',''))
        if event.get('post_type') == 'notice' and event.get('notice_type') == 'group_recall':
            message = event.get('message_id')
            if type(message) is int and -(2**63) < message < 2**63:
                with self.database(write=True) as db:
                    if not db.execute('SELECT 1 FROM groups WHERE account_id=? AND group_id=?',(account,group)).fetchone():return None
                    key = self.key(account,group,message)
                    self.suppress(db,[key])
                    db.execute('UPDATE groups SET revision=revision+1 WHERE account_id=? AND group_id=?',(account,group))
                return group
            return None
        if event.get('post_type') not in ('message','message_sent') or event.get('message_type') != 'group':return None
        sender, message, stamp = event.get('user_id'),event.get('message_id'),event.get('time')
        if (type(sender) is not int or not 0 < sender < 2**63 or type(message) is not int
                or not -(2**63) < message < 2**63 or type(stamp) is not int or not 1<=stamp<=2**53-1):return None
        with self.database() as db:
            policy=db.execute('SELECT enabled FROM groups WHERE account_id=? AND group_id=?',(account,group)).fetchone()
            if policy is None or not policy['enabled']:return None
        profile = event.get('sender')
        if profile is not None and (not isinstance(profile,dict) or str(profile.get('user_id',sender)) != str(sender)):return None
        profile = profile or {}
        name = profile.get('card') or profile.get('nickname') or ''
        if not isinstance(name,str): name = ''
        raw = event.get('message')
        if isinstance(raw,str):text,segments,kind=raw,[{'type':'raw_text'}],'raw_text'
        elif isinstance(raw,list):
            segments=[];parts=[];unsupported=False
            for s in raw:
                if not isinstance(s,dict) or not isinstance(s.get('type'),str):continue
                typ,data=s['type'],s.get('data',{})
                data=data if isinstance(data,dict) else {}
                if typ=='text' and isinstance(data.get('text'),str):
                    parts.append(data['text']);segments.append({'type':'text','text':data['text']})
                elif typ=='at':segments.append({'type':'at','qq':str(data.get('qq',''))})
                elif typ=='reply':segments.append({'type':'reply','id':str(data.get('id',''))})
                else:segments.append({'type':typ});unsupported=True # no URLs/files/credential-bearing metadata
            text=''.join(parts);kind='mixed' if unsupported else 'text'
        else:return None
        key=self.key(account,group,message)
        parents=[self.key(account,group,s['id']) for s in segments if s['type']=='reply' and s.get('id','').lstrip('-').isdigit()]
        if reply_to is not None:parents.append(self.key(account,group,reply_to))
        with self.database(write=True) as db:
            policy=db.execute('SELECT enabled FROM groups WHERE account_id=? AND group_id=?',(account,group)).fetchone()
            if policy is None or not policy['enabled']:return None
            if db.execute('SELECT 1 FROM suppressed WHERE key=?',(key,)).fetchone():return None
            for parent in parents:db.execute('INSERT OR IGNORE INTO relations VALUES (?,?)',(parent,key))
            if any(db.execute('SELECT 1 FROM suppressed WHERE key=?',(parent,)).fetchone() for parent in parents):
                self.suppress(db,[key]);return None
            count=db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,'qq',account,group,str(sender),name[:256],str(message),stamp,kind,text,
                 json.dumps(segments,ensure_ascii=False),int(time()))).rowcount
            if count:
                db.execute('UPDATE groups SET revision=revision+1 WHERE account_id=? AND group_id=?',(account,group))
            elif name:
                # Runtime acknowledgement can precede the bridge's own echo;
                # supplement an absent name without replacing saved text/identity.
                db.execute("UPDATE messages SET display_name=? WHERE key=? AND sender_id=? AND display_name=''",(name[:256],key,str(sender)))
        return None

    @staticmethod
    def record(row, *, preview=False):
        r=dict(row);r['segments']=json.loads(r['segments'])
        if preview:
            r['truncated']=len(r['text'])>2048;r['text']=r['text'][:2048]
            r.pop('segments') # stored losslessly; complete structure available in export
        return r

    def query(self, account, group, *, sender='', after=0, before=2**53-1, text='', offset=0, limit=20):
        with self.database() as db:
            self.authorize(db,account,group)
            clauses=['account_id=?','group_id=?','timestamp>=?','timestamp<=?']
            values=[account,group,after,before]
            if sender:clauses.append('sender_id=?');values.append(sender)
            if text:clauses.append('instr(text,?)>0');values.append(text) # literal Chinese substrings, no English tokenization
            db.set_progress_handler(lambda: 1 if time()>deadline else 0,10000)
            deadline=time()+2
            return [self.record(r,preview=True) for r in db.execute('SELECT * FROM messages WHERE '+' AND '.join(clauses)+
                ' ORDER BY timestamp DESC,key DESC LIMIT ? OFFSET ?',[*values,min(limit,20),offset])]

    def around(self, account, group, key, radius=2):
        with self.database() as db:
            self.authorize(db,account,group)
            center=db.execute('SELECT * FROM messages WHERE account_id=? AND group_id=? AND key=?',(account,group,key)).fetchone()
            if not center:raise ArchiveError('QQ_NOT_FOUND')
            prior=list(db.execute('SELECT * FROM messages WHERE account_id=? AND group_id=? AND (timestamp,key)<(?,?) '
                'ORDER BY timestamp DESC,key DESC LIMIT ?',(account,group,center['timestamp'],key,radius)))
            following=list(db.execute('SELECT * FROM messages WHERE account_id=? AND group_id=? AND (timestamp,key)>(?,?) '
                'ORDER BY timestamp,key LIMIT ?',(account,group,center['timestamp'],key,radius)))
            return [self.record(r,preview=True) for r in [*reversed(prior),center,*following]]

    def history_context(self, account, group, sender, question, *, history=(), exclude=''):
        """Bounded, read-only evidence from this authorized group, not owner Memory.

        Reuse the existing pure Chinese tokenizer; do not use its Memory store or
        ranking pipeline. Search full originals before excerpting, rank relevance
        before recency, and retain nearby/explicit replies with speaker identity.
        """
        personal = bool(re.search(r'我(?:的|刚才|之前|上次|周[一二三四五六日天]|\s)*.*(?:名字|姓名|叫什么|计划|准备|去哪)', question))
        generic = r'请问|帮我|我想问|告诉我|历史|当时|之前|上次|我们|群里|讨论|关于|到底|现在|为什么|为何|怎么|是否|有没有|已经|最终|最后|如何|原因|结论|决定|实现|功能|来着|说过|觉得|能不能|记得|一下|的|了|呢|吗'
        cleaned = re.sub(generic, ' ', question)
        terms = sorted(_tokens(cleaned))[:24]
        if personal:
            if any(t in question for t in ('叫什么', '名字', '姓名')):
                terms = list(dict.fromkeys(['我叫', '名字', '姓名', *terms]))[:24]
            elif any(t in question for t in ('计划', '准备', '去哪')):
                terms = list(dict.fromkeys(['计划', '准备', *terms]))[:24]
        if not terms:
            # A bare "why?" may refer to the last completed user topic. Never
            # expand from another source or a generated assistant assertion.
            previous = next((h['content'] for h in reversed(history) if h.get('role') == 'user'), '')
            terms = sorted(_tokens(re.sub(generic, ' ', previous)))[:24]

        with self.database() as db:
            self.authorize(db, account, group)
            deadline = time() + 2
            db.set_progress_handler(lambda: int(time() > deadline), 10000)
            clauses = ['account_id=?', 'group_id=?', 'message_id<>?', "text<>''"]
            values = [account, group, exclude]
            if personal:
                clauses.append('sender_id=?'); values.append(sender)
            where = ' AND '.join(clauses)
            if terms:
                score = '+'.join('CASE WHEN instr(lower(text),?)>0 THEN 1 ELSE 0 END' for _ in terms)
                anchors = list(db.execute('SELECT *, (' + score + ') AS relevance FROM messages WHERE ' + where +
                    ' ORDER BY relevance DESC,timestamp DESC,key DESC LIMIT 8', [*terms, *values]))
                anchors = [r for r in anchors if r['relevance'] > 0][:3]
            else:
                # No named topic: keep a small current-speaker fallback. A named
                # topic with no matches stays empty instead of unrelated history.
                anchors = list(db.execute('SELECT * FROM messages WHERE ' + where + ' AND sender_id=?'
                    ' ORDER BY timestamp DESC,key DESC LIMIT 3', [*values, sender]))

            selected = {r['key']: r for r in anchors}
            if not personal:
                for center in anchors:
                    related = list(db.execute('SELECT m.* FROM messages m JOIN relations r ON '
                        '(r.parent_key=? AND r.child_key=m.key) OR (r.child_key=? AND r.parent_key=m.key) '
                        'WHERE m.account_id=? AND m.group_id=? AND m.message_id<>? ORDER BY m.timestamp,m.key LIMIT 2',
                        (center['key'], center['key'], account, group, exclude)))
                    prior = list(db.execute('SELECT * FROM messages WHERE ' + where + ' AND (timestamp,key)<(?,?)'
                        ' ORDER BY timestamp DESC,key DESC LIMIT 2', [*values, center['timestamp'], center['key']]))
                    following = list(db.execute('SELECT * FROM messages WHERE ' + where + ' AND (timestamp,key)>(?,?)'
                        ' ORDER BY timestamp,key LIMIT 2', [*values, center['timestamp'], center['key']]))
                    for r in [*related, *prior, *following]:
                        if len(selected) < 8: selected.setdefault(r['key'], r)
            # The old 4 x 500 text-character ceiling remains; distribute it
            # over coherent records rather than truncating a serialized JSON.
            rows = sorted(selected.values(), key=lambda r: (r['timestamp'], r['key']))
            per_record = min(500, 2000 // max(1, len(rows)))
            evidence = []
            for r in rows:
                text = r['text']
                positions = [text.casefold().find(t) for t in terms if t in text.casefold()]
                start = max(0, min(positions) - per_record // 3) if positions else 0
                excerpt = text[start:start + per_record]
                evidence.append({'message_id': r['message_id'], 'sender_id': r['sender_id'],
                    'timestamp': r['timestamp'], 'text': excerpt,
                    'excerpted': len(excerpt) != len(text)})
            return evidence

    def revision(self, account, group):
        with self.database() as db:return self.authorize(db,account,group)['revision']

    def delete(self, account, group, scope, target, revision):
        with self.database(write=True) as db:
            if self.authorize(db,account,group)['revision']!=revision:raise ArchiveError('QQ_CONFLICT')
            extra,values=('',[]) if scope=='group' else (' AND '+('key' if scope=='message' else 'sender_id')+'=?',[target])
            where='account_id=? AND group_id=?'+extra;params=[account,group,*values]
            keys=[r[0] for r in db.execute('SELECT key FROM messages WHERE '+where,params)]
            self.suppress(db,keys)
            db.execute('UPDATE groups SET revision=revision+1'+(',enabled=0' if scope=='group' else '')+
                ' WHERE account_id=? AND group_id=?',(account,group))

    @staticmethod
    def suppress(db, keys):
        # Suppress known quoted/runtime replies as well as the removed source;
        # no derived excerpt may reintroduce its facts after privacy revocation.
        for key in keys:
            descendants=[r[0] for r in db.execute('WITH RECURSIVE related(key) AS (SELECT ? UNION '
                'SELECT child_key FROM relations JOIN related ON parent_key=related.key) SELECT key FROM related',(key,))]
            db.executemany('INSERT OR IGNORE INTO suppressed VALUES (?)',[(k,) for k in descendants])
            db.executemany('DELETE FROM messages WHERE key=?',[(k,) for k in descendants])

    def export(self, account, group):
        # Path cannot be supplied by chat, LLM or WebView. Snapshot isolation and
        # exclusive creation prevent partial overwrite of any project/user file.
        directory=self.path.parent/'exports';directory.mkdir(parents=True,exist_ok=True)
        file=directory/f'group-{group}-{secrets.token_hex(8)}.jsonl'
        partial=file.with_suffix('.partial')
        try:
            with self.database() as db:
                self.authorize(db,account,group);db.execute('BEGIN')
                with partial.open('x',encoding='utf-8') as out:
                    for r in db.execute('SELECT * FROM messages WHERE account_id=? AND group_id=? ORDER BY timestamp,key',(account,group)):
                        out.write(json.dumps(self.record(r),ensure_ascii=False)+'\n')
                    out.flush();os.fsync(out.fileno())
            os.rename(partial,file)
            return str(file)
        except (OSError,ValueError,UnicodeError):raise ArchiveError() from None
