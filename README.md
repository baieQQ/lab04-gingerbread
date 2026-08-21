# 糖果屋之後 · After the Gingerbread House

白天餵飽他們，晚上他們才不會餓到吃掉葛蕾特。

一款用 **pygame** 做的黑暗童話生存遊戲：格林童話《糖果屋》之後——兄妹燒了女巫的屋子、帶著財寶回到村子，村子鬧饑荒，村民入夜會發狂想吃掉妹妹葛蕾特。白天用行動點準備，夜晚在只有提燈照得到的黑暗裡守住她。

國立成功大學「Python Programming for Interactive Game Design」課程 Capstone 專題。

介紹網站：<https://gingerbread-after.vercel.app>

---

## 玩

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[test,display]"
.venv/bin/python -m gingerbread
```

開場選單有兩種模式：

| 模式 | 內容 |
|---|---|
| **七夜** | 主線。日夜交替、第二夜起每夜一隻頭目、有結局 |
| **無盡** | 沒有白天也沒有結局。壓力隨時間上升，撐多久算多久 |

**操作**：WASD／方向鍵移動 · 空白鍵揮燈 · Shift 衝刺 · 1 落雷 · 2 龍捲風
白天用滑鼠或鍵盤選行動卡。

---

## 驗收

```bash
.venv/bin/python -m pytest -q          # 39 個測試
.venv/bin/python -m gingerbread --check # 無畫面確定性檢查，輸出 JSON
```

`--check` 兩次執行的輸出逐位元組相同——這就是「可重現」的證據：不開視窗、不用人按鍵，也能驗證遊戲邏輯正確。

另外兩個工具：

```bash
.venv/bin/python -m gingerbread --content  # 列出所有可用的行為與特性名稱
.venv/bin/python -m gingerbread --assets   # 列出還缺哪些美術與音效檔
.venv/bin/python tools/balance.py          # 用三種程度的機器人量測難度
.venv/bin/python tools/build_font.py       # 從原始碼重建中文字型子集
```

---

## 架構

三層，層與層之間的界線就是重點：

```
src/gingerbread/
  model/   規則。不 import pygame、確定性、可離線測試
  view/    像素。只觀察狀態，從不決定結果
  app/     裝置。唯一碰到顯示、鍵盤、音效的地方
```

一幀只有一個方向：

```
事件 + 按鍵 → 動作字串
           → apply_action(state, action)   ← 模型擁有結果
           → Board.draw(state)             ← 唯讀
           → 場景畫介面
           → display.flip() → clock.tick()
```

### 契約函式（`model/contract.py`）

| 函式 | 做什麼 |
|---|---|
| `new_game(seed, meta, mode)` | 回傳全新狀態，無顯示、無裝置依賴 |
| `apply_action(state, action)` | 回傳下一個狀態，**不改動傳入的 state** |
| `is_terminal(state)` | 只有失敗或通關才回傳 True |
| `snapshot(state)` | 回傳穩定、可比對、JSON-safe 的完整證據與雜湊 |

---

## 為什麼可以擴充

夥伴之後會交來十種怪物、六隻頭目、六張地圖、技能與升級樹。這個架構的目標是**那些內容進來時不用改引擎**。

### 內容就是資料表

`model/content/` 底下每張表都是純資料。一隻普通怪物是**一行**：

```python
"beggar": MonsterSpec("beggar", "乞丐", hp=3, speed=44, radius=11, sugar=1),
```

有特殊行為的怪物是那一行，加上一個 `behaviour=` 或 `traits=` 名字：

```python
"mother": MonsterSpec(
    key="mother", name="母親", hp=3, speed=34, radius=11, sugar=2,
    traits=("splits",),
    params={"split_into": "child", "split_count": 2},
),
```

`behaviours.py` 裡已經有的詞彙可以用 `--content` 列出來。特性會**組合**——同一隻怪可以既怕光又會分裂，兩個特性互不知道對方存在。

### 打錯字會當場爆掉

匯入時就驗證每一個交叉參照：拼錯的特性名、指向不存在的地圖、會無限增殖的分裂迴圈、永遠打不死的頭目階段，全部一次列出來。

這是刻意的：**沉默失敗是最糟的失敗**。拼錯的特性名不會報錯，它只是什麼都不做，然後幾週後變成「這隻怪感覺怪怪的」。

### 沒有素材也能跑

`view/assets.py` 的規則是絕對的：**缺素材永遠不是錯誤**。每次查詢都可能回傳 `None`，每個呼叫端都必須能畫出替代的圖形。所以美術可以一張一張進來——檔名對了丟進 `assets/` 就會生效，不用改任何程式。

`--assets` 會列出目前缺的清單。

### 兩種模式是兩個導演，不是一堆 if

`model/director.py` 有 `CampaignDirector` 和 `EndlessDirector`。規則層不知道有幾夜、頭目何時來、什麼時候結束——那些是導演的事。加第三種模式是加一個類別。

---

## 確定性

課程評分要求「相同 seed + 相同動作序列 → 相同結果」。這件事比看起來難，這個版本為它做了四件事：

**整數計時。** 用浮點累加 1/60，三千步之後會得到 49.999999999998444，於是每一夜都多跑一格，而生成間隔的公式吃的就是這個會飄的值。秒數只在顯示時由 tick 導出。

**自己的亂數。** `model/rng.py` 是 splitmix64，狀態只有一個 64 位元整數。理由有四個：複製成本歸零（`random.Random` 的 625 字狀態佔掉每幀一半的複製時間）、亂數位置可以直接進快照、純整數運算跨平台逐位元一致、以及可以切成互不干擾的子流——這樣夥伴改怪物表不會位移事件的亂數，把過去錄下的 seed 全部作廢。

**不碰平台的三角函數。** `math.cos / sin / atan2 / asin` 是丟給作業系統的數學函式庫的，macOS 與 WebAssembly 可以差一個最低位元。實測把 cos/sin 各推一個 ULP，72 場完整夜晚有 64 場結果分岔。所以揮燈的錐形判定改用點積與外積，只有加減乘除；環形排列的結果四捨五入到小數第九位。`math.hypot` 不用動——那個是 CPython 自己實作的。

**看得見的證據。** `snapshot()` 輸出每一隻怪的座標與血量、玩家所有計時器、所有亂數子流的位置，浮點用 `repr()` 而不是四捨五入。舊版只數怪物數量、座標只留三位小數，結果是兩場已經分岔的執行可以連續幾千格都比對相同——**測不出失敗的證據不是證據**。

`tests/test_content.py` 另外用 AST 掃描確保沒有任何規則層的檔案 import 了 `pygame`、`random` 或時鐘。

---

## 網頁版

```bash
.venv/bin/python -m pip install pygbag fonttools
.venv/bin/python build_web.py
```

中文字型用 `tools/build_font.py` 從系統字型子集化——**它會掃描原始碼裡所有字串**，所以夥伴加了新怪物名字之後重跑一次就會自動涵蓋。手動維護字表一定會落後，而缺字不會報錯，只會安靜地畫成空白。

> 部署到 Vercel 等靜態平台時**不要**加 `Cross-Origin-Embedder-Policy: require-corp`——會擋掉 pygbag 的 CDN 資源，導致頁面卡在載入畫面。

---

## 目前的狀態

`model/content/` 底下全部是**佔位內容**，用來讓引擎有東西可跑。夥伴的版本一到就整段取代。

目前用機器人量到的難度（`tools/balance.py`，五個 seed）：

| | 七夜 | 無盡 |
|---|---|---|
| 粗心（亂揮、直接撞上去） | 第 1 夜 | 約 1.4 分 |
| 謹慎（抓距離才揮） | 第 2 夜 | 約 4 分 |
| 熟練（會衝刺、會補血） | 第 2 夜 | 約 4 分 |

第一夜謹慎玩家五場全過、粗心玩家全滅——教學關該有的樣子。第二夜是第一場頭目戰，目前是新的牆。

已知還沒到位的地方：

- **無盡模式的後段**還撐不到目標的 6–10 分鐘（目前約 4 分鐘）。原因量測過了：一場結束時場上約三十隻，也就是玩家的擊殺速度到頂（揮燈冷卻下限 0.5 秒、攻擊力上限 6）而生成持續加速。要補上這個差距需要玩家還沒有的**能力**——更廣的弧、一次打多隻之類——那是內容設計，不是調常數。
- **音效層還沒開始**。`view/assets.py` 已經準備好載入 `assets/sounds/`，但還沒有接點。
- **序章壓縮成一頁**，不是網頁版的五章。
- **謹慎與熟練兩種打法目前打不出差距**。兩者都停在第 2 夜／4 分鐘，代表現在的內容還沒有獎勵「更會玩」的機制——衝刺、走位、法術時機都還不夠關鍵。這也是內容設計要解的，不是常數。

素材清單與移植規劃見專案外的 `素材清單與pygame移植規劃.md`；設計定案見 `遊戲設計定案.md`。
