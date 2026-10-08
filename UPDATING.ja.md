# 日本語版の更新

`origin`は日本語版フォーク、`upstream`は本家の`zhongerxin/iPhone-use`です。Gitクローンから更新します。端末・署名・ログ・WDAのビルドはGitの外にあり、再インストール時もMCPに登録した環境設定を引き継ぎます。

## 本家の更新を確認する

クローンのルートで実行します。ファイルやインストール済み版は変更しません。

```sh
python3 scripts/update.py --check
```

## 日本語化を維持して取り込む

未コミットの変更を保存してから実行します。初回は本家のリモートを自動登録します。

```sh
python3 scripts/update.py --prepare
```

`codex/upstream-...`という確認用ブランチを作り、本家の`main`をマージします。競合がなくてもコミット前で止まります。日本語版の公開ブランチとインストール済み版はそのままです。

1. 競合を解消し、新しいREADME・スキル・ツール説明・画面文言を翻訳します。上流の機能修正は保持します。元の中国語READMEは`README.zh-CN.md`へ反映し、`README.md`と`README.ja.md`を揃えます。
2. `git diff HEAD`で確認し、下のビルドとテストを実行します。実行データの保存先はGit外にします。
3. 確認後に`git add`と`git commit`でマージを確定します。スクリプトが表示した元のブランチへ戻り、`git merge --ff-only <確認用ブランチ名>`で取り込みます。
4. 公開する場合は`git push origin HEAD:main`で日本語版フォークを更新します。`sh scripts/install.sh`でローカルへ再導入し、チャットを再接続します。

```sh
npm ci --prefix ui --no-audit --no-fund
npm run build --prefix ui
sh scripts/check.sh
node --test ui/tests/widget.test.mjs
```

マージを取り消す場合は確認用ブランチで`git merge --abort`を実行し、元のブランチへ戻ります。自動でコミット・push・再インストール・定期実行する機能はありません。

Codexには次のように依頼できます。

> この日本語版iPhone Useについて、本家の更新を確認し、変更があれば別ブランチへ取り込んでください。新しい表示も日本語にし、競合を解消してビルドとテストを確認してください。問題がなければ日本語版フォークのmainを更新し、このMacへ再インストールしてください。既存の端末・署名・実行データは引き継いでください。

## 日本語版フォークの公開済み更新を入れる

`origin/main`を追跡するローカルの`main`で、変更を保存してから実行します。

```sh
git pull --ff-only origin main
sh scripts/install.sh
```

再導入時に、既存のMCP環境変数を保持します。別の実行ディレクトリやXcodeへ変更する場合だけ、`IPHONE_USE_STATE_DIR`や`DEVELOPER_DIR`をインストールコマンドへ明示して上書きしてください。
