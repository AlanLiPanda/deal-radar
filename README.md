# 特价雷达

买菜特价雷达，数据来自附近超市的 Flipp 传单。

`grocery-deals/` 里的 `products.json` 决定搜什么商品、用哪个邮编，`data.json` 是抓到的结果。

## 更新数据

GitHub Actions 每天温哥华早上 7 点自动跑 `update.py`，提交新的 `data.json` 并重新发布网页。
想马上更新：打开仓库的 Actions → Update deals and publish → Run workflow。

在自己电脑上跑：

```bash
python3 update.py grocery-deals
```
