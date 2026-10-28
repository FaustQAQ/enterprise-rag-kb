
import { useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import './App.css'
import {
  ApiError,
  API_BASE_URL,
  askQuestion,
  embedDocument,
  getHealth,
  listDocuments,
  searchDocuments,
  uploadDocument,
  type ChatSource,
  type DocumentSummary,
  type RetrievalHit,
} from './api'

type Page = '工作台' | '文档管理' | '知识检索' | '智能问答' | '系统设置'

type DocumentItem = {
  id: number
  name: string
  type: string
  chunks: number
  status: string
  date: string
}

type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
  sources?: ChatSource[]
}

const navigation: { label: Page; icon: string }[] = [
  { label: '工作台', icon: '▦' },
  { label: '文档管理', icon: '▤' },
  { label: '知识检索', icon: '⌕' },
  { label: '智能问答', icon: '✳' },
  { label: '系统设置', icon: '⚙' },
]

function toDocumentItem(document: DocumentSummary): DocumentItem {
  return {
    id: document.id,
    name: document.filename,
    type: document.file_type.toUpperCase(),
    chunks: document.chunk_count,
    status: document.status === 'processed' ? '已完成' : document.status,
    date: new Date(document.updated_at || document.created_at).toLocaleDateString('zh-CN'),
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return '请求失败，请稍后重试。'
}

function renderInlineMarkdown(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|__[^_]+__)/g).map((part, index) => {
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    return <span key={index}>{part}</span>
  })
}

function MarkdownAnswer({ content }: { content: string }) {
  const lines = content.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let listItems: ReactNode[] = []
  let listKind: 'ul' | 'ol' | null = null

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push(listKind === 'ol' ? <ol key={'list-' + blocks.length}>{listItems}</ol> : <ul key={'list-' + blocks.length}>{listItems}</ul>)
      listItems = []
      listKind = null
    }
  }

  lines.forEach((line, index) => {
    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    const unorderedItem = line.match(/^\s*[-*+]\s+(.+)$/)
    const orderedItem = line.match(/^\s*\d+[.)]\s+(.+)$/)

    if (unorderedItem || orderedItem) {
      const nextListKind = orderedItem ? 'ol' : 'ul'
      if (listKind && listKind !== nextListKind) flushList()
      listKind = nextListKind
      listItems.push(<li key={'item-' + index}>{renderInlineMarkdown((unorderedItem || orderedItem)?.[1] || '')}</li>)
      return
    }

    flushList()
    if (heading) {
      const level = Math.min(heading[1].length, 6)
      const Heading = ('h' + level) as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'
      blocks.push(<Heading key={'heading-' + index}>{renderInlineMarkdown(heading[2])}</Heading>)
    } else if (line.trim()) {
      blocks.push(<p key={'paragraph-' + index}>{renderInlineMarkdown(line)}</p>)
    } else {
      blocks.push(<br key={'break-' + index} />)
    }
  })

  flushList()
  return <div className="answer-markdown">{blocks}</div>
}

function uniqueSources(sources: ChatSource[]): ChatSource[] {
  const seenChunkIds = new Set<number>()
  return sources.filter((source) => {
    if (seenChunkIds.has(source.chunk_id)) return false
    seenChunkIds.add(source.chunk_id)
    return true
  })
}

function App() {
  const [page, setPage] = useState<Page>('工作台')
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [search, setSearch] = useState('')
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [notice, setNotice] = useState('')
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [isChatting, setIsChatting] = useState(false)
  const [searchResults, setSearchResults] = useState<RetrievalHit[]>([])
  const [serviceStatus, setServiceStatus] = useState<'checking' | 'online' | 'offline'>('checking')

  async function refreshDocuments() {
    setIsLoadingDocuments(true)
    try {
      const response = await listDocuments()
      setDocuments(response.items.map(toDocumentItem))
    } catch (error) {
      setNotice(getErrorMessage(error))
    } finally {
      setIsLoadingDocuments(false)
    }
  }

  useEffect(() => {
    void refreshDocuments()
    void getHealth()
      .then(() => setServiceStatus('online'))
      .catch(() => setServiceStatus('offline'))
  }, [])

  function selectPage(nextPage: Page) {
    setPage(nextPage)
    setNotice('')
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (!files?.length) return

    setIsUploading(true)
    const failures: string[] = []
    let uploadedCount = 0
    try {
      for (const file of Array.from(files)) {
        try {
          const document = await uploadDocument(file)
          uploadedCount += 1
          try {
            await embedDocument(document.id)
          } catch (error) {
            failures.push(`${file.name} 已上传，但向量化失败：${getErrorMessage(error)}`)
          }
        } catch (error) {
          failures.push(`${file.name} 上传失败：${getErrorMessage(error)}`)
        }
      }
      await refreshDocuments()
      setNotice(
        failures.length
          ? `${uploadedCount} 个文件已上传。${failures.join('；')}`
          : `${uploadedCount} 个文件已上传并完成向量化。`,
      )
    } finally {
      setIsUploading(false)
    }
    event.target.value = ''
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!search.trim()) return
    setIsSearching(true)
    setSearchResults([])
    try {
      const response = await searchDocuments({ query: search.trim(), top_k: 10 })
      setSearchResults(response.hits)
      setNotice(
        response.hits.length
          ? `检索完成，共返回 ${response.hits.length} 条结果。`
          : '检索完成，没有找到符合条件的知识片段。',
      )
    } catch (error) {
      setNotice(getErrorMessage(error))
    } finally {
      setIsSearching(false)
    }
  }

  async function handleChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!question.trim()) return

    const currentQuestion = question.trim()
    setMessages((current) => [
      ...current,
      { role: 'user', text: currentQuestion },
    ])
    setQuestion('')
    setIsChatting(true)
    try {
      const response = await askQuestion({ question: currentQuestion, top_k: 5 })
      setMessages((current) => [
        ...current,
        { role: 'assistant', text: response.answer, sources: response.sources },
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: 'assistant', text: `请求失败：${getErrorMessage(error)}` },
      ])
    } finally {
      setIsChatting(false)
    }
  }

  const totalChunks = documents.reduce((sum, document) => sum + document.chunks, 0)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div>
            <div className="brand-name">KnowledgeHub</div>
            <div className="brand-subtitle">ENTERPRISE RAG</div>
          </div>
        </div>

        <div className="workspace-label">工作空间</div>
        <div className="workspace">
          <span className="workspace-icon">企</span>
          <span>企业知识库</span>
          <span className="workspace-arrow">⌄</span>
        </div>

        <div className="nav-label">功能菜单</div>
        <nav className="navigation">
          {navigation.map((item) => (
            <button
              key={item.label}
              className={`nav-item ${page === item.label ? 'active' : ''}`}
              onClick={() => selectPage(item.label)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {page === item.label && <span className="active-dot" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-indicator">
            <span className={`status-dot service-dot ${serviceStatus}`} />
            <span>{serviceStatus === 'online' ? '后端服务已连接' : serviceStatus === 'checking' ? '正在检查后端' : '后端服务不可用'}</span>
          </div>
          <div className="profile">
            <div className="avatar">A</div>
            <div>
              <div className="profile-name">管理员</div>
              <div className="profile-role">知识库管理者</div>
            </div>
            <span className="profile-more">···</span>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <span>企业知识库</span>
            <span className="breadcrumb-separator">/</span>
            <strong>{page}</strong>
          </div>
          <div className="topbar-right">
            <span className="environment-badge">DEVELOPMENT</span>
            <span className="topbar-divider" />
            <span className="admin-avatar">A</span>
            <span className="topbar-admin">管理员</span>
          </div>
        </header>

        <div className="page-content">
          {notice && (
            <div className="notice">
              <span>ⓘ</span>
              <span>{notice}</span>
              <button onClick={() => setNotice('')}>×</button>
            </div>
          )}

          {page === '工作台' && (
            <>
              <section className="welcome-row">
                <div>
                  <div className="eyebrow">KNOWLEDGE INTELLIGENCE PLATFORM</div>
                  <h1>工作台</h1>
                  <p>管理企业知识资产，让知识检索与智能问答更简单。</p>
                </div>
                <button className="primary-button" onClick={() => selectPage('文档管理')}>
                  <span>＋</span> 添加知识文档
                </button>
              </section>

              <section className="metric-grid">
                <div className="metric-card">
                  <div className="metric-top">
                    <span>知识文档</span>
                    <span className="metric-icon purple">▤</span>
                  </div>
                  <div className="metric-value">{documents.length}</div>
                  <div className="metric-foot">当前列表中的文档</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top">
                    <span>知识分块</span>
                    <span className="metric-icon blue">▦</span>
                  </div>
                  <div className="metric-value">{totalChunks}</div>
                  <div className="metric-foot">已记录的文本分块</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top">
                    <span>向量模型</span>
                    <span className="metric-icon green">⌘</span>
                  </div>
                  <div className="metric-value model-value">后端配置</div>
                  <div className="metric-foot">具体模型由后端环境决定</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top">
                    <span>服务状态</span>
                    <span className="metric-icon orange">⌁</span>
                  </div>
                  <div className="metric-value service-value">
                    <span className={`status-dot service-dot ${serviceStatus}`} />
                    {serviceStatus === 'online' ? '后端已连接' : serviceStatus === 'checking' ? '检查中' : '连接失败'}
                  </div>
                  <div className="metric-foot">通过 GET /health 检查</div>
                </div>
              </section>

              <section className="content-grid">
                <div className="panel recent-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>最近的知识文档</h2>
                      <p>查看当前工作空间的文档记录</p>
                    </div>
                    <button className="text-button" onClick={() => selectPage('文档管理')}>
                      查看全部 →
                    </button>
                  </div>
                  <DocumentTable documents={documents.slice(0, 4)} />
                </div>

                <div className="panel quick-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>快速开始</h2>
                      <p>选择一项操作，继续探索知识库</p>
                    </div>
                  </div>
                  <button className="quick-action" onClick={() => selectPage('文档管理')}>
                    <span className="quick-icon purple">↥</span>
                    <span className="quick-copy">
                      <strong>上传知识文档</strong>
                      <small>将企业资料整理到知识库</small>
                    </span>
                    <span className="quick-arrow">→</span>
                  </button>
                  <button className="quick-action" onClick={() => selectPage('知识检索')}>
                    <span className="quick-icon blue">⌕</span>
                    <span className="quick-copy">
                      <strong>检索知识片段</strong>
                      <small>查看与问题相关的文本内容</small>
                    </span>
                    <span className="quick-arrow">→</span>
                  </button>
                  <button className="quick-action" onClick={() => selectPage('智能问答')}>
                    <span className="quick-icon green">✳</span>
                    <span className="quick-copy">
                      <strong>体验智能问答</strong>
                      <small>基于知识库组织问题与答案</small>
                    </span>
                    <span className="quick-arrow">→</span>
                  </button>
                </div>
              </section>
            </>
          )}

          {page === '文档管理' && (
            <section>
              <div className="welcome-row">
                <div>
                  <div className="eyebrow">DOCUMENT MANAGEMENT</div>
                  <h1>文档管理</h1>
                  <p>集中管理知识文件，查看文档与分块状态。</p>
                </div>
                <label className={`primary-button upload-button ${isUploading ? 'loading' : ''}`}>
                  {isUploading ? '上传中...' : '＋ 上传文档'}
                  <input type="file" multiple accept=".txt,.pdf,.docx" onChange={handleUpload} disabled={isUploading} />
                </label>
              </div>
              <div className="panel document-panel">
                <div className="panel-heading">
                  <div>
                    <h2>全部文档</h2>
                    <p>当前显示 {documents.length} 条后端文档记录</p>
                  </div>
                  <span className="environment-badge">真实接口</span>
                </div>
                {isLoadingDocuments ? <div className="loading-state">正在加载文档...</div> : <DocumentTable documents={documents} />}
                <p className="panel-footnote">上传后会调用后端文档接口，并尝试生成向量；向量服务未配置时会显示对应错误。</p>
              </div>
            </section>
          )}

          {page === '知识检索' && (
            <section>
              <div className="welcome-row">
                <div>
                  <div className="eyebrow">SEMANTIC RETRIEVAL</div>
                  <h1>知识检索</h1>
                  <p>使用自然语言查找知识库中相关的文本片段。</p>
                </div>
              </div>
              <div className="panel retrieval-panel">
                <div className="search-illustration">⌕</div>
                <h2>搜索企业知识</h2>
                <p>输入问题，检索相关文档内容与来源。</p>
                <form className="search-form" onSubmit={handleSearch}>
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="例如：公司的差旅报销制度是什么？"
                  />
                  <button className="primary-button" type="submit" disabled={isSearching}>
                    {isSearching ? '检索中...' : '开始检索 →'}
                  </button>
                </form>
                <div className="search-hint">检索接口：POST /api/v1/retrieval/search</div>
                {isSearching && <div className="loading-state">正在查询后端检索服务...</div>}
                {!isSearching && searchResults.length > 0 && (
                  <div className="retrieval-results">
                    {searchResults.map((result) => (
                      <article className="retrieval-result" key={result.chunk_id}>
                        <div className="retrieval-result-meta">
                          <span>文档 ID：{result.document_id}</span>
                          <span>分块：{result.chunk_index}</span>
                          <strong>相关度 {result.score.toFixed(4)}</strong>
                        </div>
                        <p>{result.text}</p>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {page === '智能问答' && (
            <section>
              <div className="welcome-row">
                <div>
                  <div className="eyebrow">RETRIEVAL AUGMENTED GENERATION</div>
                  <h1>智能问答</h1>
                  <p>基于企业知识文档，探索有来源依据的问答体验。</p>
                </div>
                <span className="environment-badge">后端接口</span>
              </div>
              <div className="panel chat-panel">
                <div className="chat-heading">
                  <div className="chat-logo">✳</div>
                  <div>
                    <h2>企业知识助手</h2>
                    <p>回答来自后端 RAG 编排及当前配置的 LLM 服务。</p>
                  </div>
                </div>
                <div className="chat-messages">
                  {messages.length === 0 && (
                    <div className="empty-chat">
                      <div className="empty-chat-icon">✳</div>
                      <h3>有什么可以帮你？</h3>
                      <p>试着询问企业制度、报销要求或文档中的具体信息。</p>
                      <button onClick={() => setQuestion('公司的差旅报销制度是什么？')}>
                        公司的差旅报销制度是什么？
                      </button>
                    </div>
                  )}
                  {messages.map((message, index) => (
                    <div key={index} className={`chat-message ${message.role}`}>
                      <div className="message-role">
                        {message.role === 'user' ? '你' : '知识助手'}
                      </div>
                      {message.role === 'assistant' ? <MarkdownAnswer content={message.text} /> : <div>{message.text}</div>}
                      {message.sources && message.sources.length > 0 && (
                        <div className="source-list">
                          <strong>来源</strong>
                          {uniqueSources(message.sources).map((source) => (
                            <div className="source-item" key={source.chunk_id}>
                              <div className="source-meta">
                                {source.filename || `文档 ${source.document_id}`} · 分块 {source.chunk_index} · 相关度 {source.score.toFixed(4)}
                              </div>
                              <div className="source-text">{source.text}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {isChatting && <div className="loading-state">知识助手正在检索并生成回答...</div>}
                </div>
                <form className="chat-form" onSubmit={handleChat}>
                  <input
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="输入你的问题..."
                  />
                  <button className="primary-button" type="submit" disabled={isChatting}>
                    {isChatting ? '生成中...' : '发送 ↑'}
                  </button>
                </form>
                <div className="chat-disclaimer">回答和来源由当前后端配置决定；Mock 模式仅用于本地开发与演示。</div>
              </div>
            </section>
          )}

          {page === '系统设置' && (
            <section>
              <div className="welcome-row">
                <div>
                  <div className="eyebrow">SYSTEM CONFIGURATION</div>
                  <h1>系统设置</h1>
                  <p>查看当前前端使用的服务地址与技术栈。</p>
                </div>
              </div>
              <div className="panel settings-panel">
                <h2>服务配置</h2>
                <div className="setting-row">
                  <div><strong>前端开发服务器</strong><small>Vite 本地开发环境</small></div>
                  <span className="setting-value">http://localhost:5173</span>
                </div>
                <div className="setting-row">
                  <div><strong>后端 API 地址</strong><small>由前端 API 层统一管理</small></div>
                  <span className="setting-value">{API_BASE_URL}</span>
                </div>
                <div className="setting-row">
                  <div><strong>前端框架</strong><small>TypeScript + React</small></div>
                  <span className="setting-value">React</span>
                </div>
                <div className="setting-row">
                  <div><strong>服务状态</strong><small>当前页面启动时检查</small></div>
                  <span className="setting-value">{serviceStatus === 'online' ? 'online' : serviceStatus}</span>
                </div>
              </div>
            </section>
          )}

          <footer className="page-footer">
            <span>Enterprise RAG Knowledge Base</span>
            <span>已接入文档、检索与 Chat API</span>
          </footer>
        </div>
      </main>
    </div>
  )
}

function DocumentTable({ documents }: { documents: DocumentItem[] }) {
  if (documents.length === 0) {
    return <div className="table-empty">暂无文档，请先添加文件。</div>
  }

  return (
    <div className="table-wrap">
      <table className="document-table">
        <thead>
          <tr>
            <th>文档名称</th>
            <th>分块数</th>
            <th>状态</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => (
            <tr key={document.id}>
              <td>
                <div className="file-cell">
                  <span className="file-icon">{document.type === 'PDF' ? 'P' : 'T'}</span>
                  <div>
                    <strong>{document.name}</strong>
                    <small>文档 ID：{document.id}</small>
                  </div>
                </div>
              </td>
              <td>{document.chunks}</td>
              <td>
                <span className={`status-badge ${document.status === '已完成' ? 'completed' : 'pending'}`}>
                  <span className="status-dot" />
                  {document.status}
                </span>
              </td>
              <td className="date-cell">{document.date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default App
