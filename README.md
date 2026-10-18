# Taiwan Momentum Scanner v2 — 新獨立專案

> **重要**：這是一套全新策略，追蹤起點預設為 **2026-10-19**。不會改動你既有的 `tw-momentum-screener` Repository。所有輸出均為盤後收盤價的理論觀察與報酬，並非下單系統。

## 1. 策略定義（嚴格不等式）

### 必要條件 A（全部成立）

- **A1**：近 3 個交易日平均成交量 **>** 近 12 個交易日平均成交量。兩者皆包含今天；股數先在程式內計算，展示換算為「張」（1000 股）。
- **A2**：SMA20 **>** SMA60 **>** SMA120（均以未還原每日收盤價計算）。
- **A3**：`(收盤價 > 200 AND 當日成交量 > 6000 張) OR (50 < 收盤價 < 200 AND 當日成交量 > 15000 張)`。等於 50 或 200 元不觸發；「等於門檻量」亦不觸發。

### 選擇性條件 B（任一成立即可）

- **B1 ETF 持股增加**：指定 ETF 任一支在 *該交易日* 揭露的某檔普通股 **quantityChange > 0 股**。預設追蹤 ETF `0050,00981A,00403A`；你可修改 GitHub Actions 的 `ETF_SYMBOLS` 環境變數。此判斷是 **ETF 的持有股數增加**，而非權重增加，也不等於能證明主動買入。**無法核驗揭露日時顯示未知**，不以 B1 作進場依據。
- **B2 三日均價突破**：今天收盤 **> 昨天、前天、大前天的收盤價平均**（不含今天）。
- **B3 強勢 RSI + KD**：`RSI14(t) > RSI14(t-1) > 70`、`K(t) > D(t) > 50`、`K(t) > K(t-1)`，三者必須同時成立。RSI 使用 Wilder 14；KD 使用 9 日 RSV 與 **9,3,3** 平滑 K/D，起始 K=D=50；當 9 日最高與最低相等時 RSV=50。
- **B4 漲幅條件**：最近兩個交易日 **每日收盤對前一日收盤的漲幅都嚴格 >5%**，**或** 今天收盤價相較 **5 個交易日前收盤價** 累計漲幅 **>20%**。

### 剔除條件 E（任一成立即剔除）

- **E1**：今天收盤 **< SMA10**。
- **E2 爆量長黑 K**：今日量 **> 昨日量**；且 `(今日開盤價－今日收盤價) / 今日開盤價 >= 5%`；且 **今天收盤價 < 昨日最低價**。這裡「長黑」採台股綠 K 下跌實體的 5% 定義；你可在 `engine.py` 修改 `BEAR_VOLUME_RATIO`、`BEAR_BODY_FRACTION`。

**當日同時有進場與剔除訊號** → 放入 `blocked_entries.csv`，不進場。

> 四組 B1～B4 是獨立的選擇性條件；你原本訊息寫「三組」但實際列了四組，這版四組全部實作。

## 2. 全市場範圍與資料來源

- TWSE 上市＋TPEx 上櫃的 **四碼純數字普通股**，不限制產業（本版沒有沿用上一版的「只限電子產業」）；公司身分需能由交易所官方公司名冊辨識。
- 2025 年至今歷史日線：社群 GitHub `yukishirotsubasa/tw-stock-data-release` 年度 ZIP／週 ZIP，據稱取自 TWSE／TPEx 官方收盤行情；最新日線則由 TWSE、TPEx 官方盤後 OpenAPI 查核及補齊。
- 最新與歷史皆為 **未還原 OHLCV**；並未調整股票分割、除權息，因此不等同總報酬或真正的還原 K 線回測。
- ETF 持股 B1：Fugle `GET /ownership/etf-holdings/{symbol}`，需要**具備權限的 API key / 可能需付費**；也能以 `--etf-csv` 提供經自行驗證的 CSV。其變動是對上一個 *有揭露日*，不保證前一交易日；**沒有驗證資料實際公布時間**，因此歷史 ETF B1 屬於事後訊號，不能直接作無前視偏誤的回測。
- 不會因 ETF API 失敗而臆測 ETF 未加碼；沒有 API 時 B1 顯示 unknown，B2～B4 仍可觸發入選。
- 排程僅在今天已有雙市場完整收盤行情時發布最新報告。**手動執行（workflow_dispatch）** 即使是週末、國定假日，或今日尚未有完整收盤資料，也允許重印**最近一個已完成交易日**的報告；絕不將該報告標示為今日新行情。資料日期不符或任一市場資料過少時仍拒絕不完整市場名單。

## 3. 盤後報告（GitHub Actions Artifacts）

- `report.html`：瀏覽器開啟，固定 **一、觀察清單；二、新增、剔除清單；三、連續收益**。觀察清單包含代號、名稱、收盤、成交量、均量倍率、今日漲跌幅、MA20/60/120、RSI、K/D、入選原因、10 日收盤價小折線圖。
- `watchlist.csv`：最新仍在追蹤的股票，含 B/E 條件與追蹤天數。
- `added.csv`／`removed.csv`／`blocked_entries.csv`：當天進、出名單與同日遭汰除禁止入選。
- `continuous_returns.csv`：仍在觀察清單至少 2 個有報價交易日的股票，依自入選日收盤價至最新收盤價的理論累積報酬排序。
- `trades.csv`：已完成的假設收盤進、收盤出交易紀錄；`daily_watchlist.csv`、`changes.csv`：逐日名單狀態，可做事後統計；`metadata.json`：來源及 ETF 完整性聲明。

追蹤從 `TRACKING_START` 之後每次重算，避免 GitHub Actions runner 暫存資料遺失；回測早於起點的日線只用來計算技術指標，不會出現在追蹤名單中。**每次執行皆以同一份歷史資料重播，第三方歷史資料修改會影響既有報酬。** 停牌或沒有新報價的股票不會偽造新價格，屬於資料陳舊，報告另行保留 stale 標記。

## 4. 建立新 Repository（Windows、GitHub Desktop 最容易）

1. 到 [GitHub](https://github.com/new) 新建私有 Repository，例如 `tw-momentum-scan-v2`，可先選 **不建立 README**。
2. 下載本專案 ZIP 解壓縮。**要保留隱藏的 `.github/workflows/daily_scan.yml`**，不能只上傳 `screener.py`。
3. 以 [GitHub Desktop](https://desktop.github.com/) 把新 Repository clone 到電腦。在專案本機資料夾內，複製本 ZIP 解出的所有檔案與子資料夾，包含 `.github`、`tests`、`engine.py` 等。
4. GitHub Desktop 填 commit 訊息 `Initialize momentum scan v2`，按 **Commit to main → Push origin**。推送後在 GitHub 的 Code 頁應能看到 `.github/workflows/daily_scan.yml`。
5. 若需要 B1 ETF，自行申請 Fugle API key（必須具備 ETF Holdings 端點權限）。到 Repository → **Settings → Secrets and variables → Actions → New repository secret**，名稱 `FUGLE_API_KEY`，值為個人的密鑰；**不要上傳到程式碼或聊天室**。
6. 到 **Actions → Taiwan Momentum V2 Daily → Run workflow** 手動測試。**手動執行**在非交易日會使用最近完整交易日行情產出回顧報告；**自動排程**在休市日／未公布新行情時仍會 SKIP。報告追蹤起點固定為 2026-10-19，因此該日期之前不會有新策略入選紀錄。正常交易日 18:30（台灣時間）GitHub 會嘗試自動執行，可能延遲。
7. 成功執行的 Actions 詳細頁 → **Artifacts** → `momentum-v2-report-N` → 下載 ZIP，解壓縮雙擊 `report.html`。

> 此專案是新 ZIP，需要在你的 GitHub 帳號建立新 Repository 後自行 push。系統沒有替你建立或修改任何現有 GitHub Repository。

## 5. 開發機執行

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python screener.py --cache data/archive --output output
```

公開歷史 ZIP 第一次執行可能超過數分鐘，GitHub Actions 設定 55 分鐘上限。若沒有最新交易日資料會安全停止。

可使用 **本地 CSV** 測試（這只能證明程式流程，不能聲稱市場資料完整）：

```bash
python screener.py --csv examples/sample_prices.csv \
    --sectors examples/sample_companies.csv --as-of 2026-10-23 \
    --start 2026-10-19 --output output-demo
```

ETF 本地 CSV 欄位：`date,etf,code,quantity_change`；欲連用，再追加 `--etf-csv your_etf_data.csv`。不同 ETF 的缺失日不可自行補 0；請核實資料揭露日。

## 6. 特別注意的回測偏誤

1. 每日收盤後才知道 K 線終值，但假設**當日收盤價進場/出場**，會造成成交時間不實際。真實回測應另加「次日開盤執行＋交易成本＋滑價＋停牌/漲跌停無法成交」。
2. ETF 成分股揭露的 **查詢日期 != 必然當日收盤前可觀測**。不能直接拿今日 ETF 資訊假設今日收盤前就知道。
3. 未還原日線遇到除權息／股本變動會扭曲均線與報酬；如需嚴格回測請替換資料層為可驗證的還原價格（各期間一致）。
4. 建議將每日 `output/` Artifacts 或在個人儲存空間另行備份，歷史來源若補正會重算結果。
5. 日期條件與成交量全用明確的 `>`，不會把「等於」誤當作穿越。
