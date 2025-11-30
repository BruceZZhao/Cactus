# 如何提交 PR 到 GitHub

## 步骤 1: Fork 仓库（如果还没有）

1. 访问 https://github.com/BruceZZhao/Cactus
2. 点击右上角的 "Fork" 按钮
3. 等待 Fork 完成

## 步骤 2: 在 Cactus-main 目录中初始化 Git

```powershell
cd D:\Research\Agent\Cactus-main\Cactus-main

# 初始化 Git（如果还没有）
git init

# 添加远程仓库（替换 YOUR_USERNAME 为你的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/Cactus.git
git remote add upstream https://github.com/BruceZZhao/Cactus.git
```

## 步骤 3: 创建新分支

```powershell
# 创建并切换到新分支
git checkout -b feature/rag-thinker-integration
```

## 步骤 4: 添加文件并提交

```powershell
# 添加所有文件
git add .

# 提交更改
git commit -m "feat: Add RAG and Thinker Agent integration

- Add RAG (Retrieval-Augmented Generation) for character profiles
- Add Thinker Agent for conversation history summarization
- Add new API endpoints: /set-character, /set-script, /sessions/{id}/settings
- Update frontend to support RAG and character/script selection
- Add vector database encoding script for character profiles
- Update README with RAG and Thinker Agent documentation"
```

## 步骤 5: 推送到你的 Fork

```powershell
# 首次推送，设置上游分支
git push -u origin feature/rag-thinker-integration
```

## 步骤 6: 在 GitHub 上创建 PR

1. 访问你的 Fork: `https://github.com/YOUR_USERNAME/Cactus`
2. 你会看到一个提示 "Compare & pull request"，点击它
3. 或者访问: `https://github.com/BruceZZhao/Cactus/compare/main...YOUR_USERNAME:Cactus:feature/rag-thinker-integration`

4. 填写 PR 信息：
   - **Title**: `feat: Add RAG and Thinker Agent integration`
   - **Description**:
   ```markdown
   ## 新增功能
   
   ### RAG (Retrieval-Augmented Generation)
   - 为角色配置文件添加向量数据库支持
   - 使用 Qdrant 存储和检索角色背景信息
   - 通过 `backend/rag/encode_with_chunk_and_para.py` 构建向量库
   - 在 LLM 提示中自动注入相关角色信息
   
   ### Thinker Agent
   - 后台智能体，自动总结对话历史
   - 当对话长度超过 6 条消息时触发
   - 生成对话摘要和下一个话题建议
   - 使用独立的 Gemini 模型进行推理
   
   ### 新增 API 端点
   - `POST /sessions/{session_id}/settings` - 配置会话设置
   - `POST /set-character` - 设置角色
   - `POST /set-script` - 设置脚本
   
   ### 前端更新
   - 自动配置 RAG 模式和角色/脚本选择
   - 支持通过 UI 切换角色和脚本
   
   ## 测试
   - ✅ RAG 功能测试通过
   - ✅ Thinker Agent 功能测试通过
   - ✅ 前端集成测试通过
   - ✅ 完整项目运行测试通过
   
   ## 配置要求
   - 需要设置 `CLEAN_RAG_ENABLED=true` 启用 RAG
   - 需要运行 `python backend/rag/encode_with_chunk_and_para.py` 构建向量库
   ```

5. 点击 "Create pull request"

## 注意事项

- 确保 `.env` 文件不会被提交（已在 `.gitignore` 中）
- 确保 `venv/` 和 `node_modules/` 不会被提交（已在 `.gitignore` 中）
- 确保向量数据库数据文件不会被提交（已在 `.gitignore` 中）
- 所有代码注释都是英文且简洁明了

