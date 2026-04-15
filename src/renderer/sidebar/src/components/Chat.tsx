import React, { useState, useRef, useEffect, useLayoutEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import {
    ArrowUp,
    Check,
    Database,
    FileCode2,
    FileSpreadsheet,
    FileText,
    Globe,
    ListFilter,
    Plus,
    Presentation,
    Trash2,
    X
} from 'lucide-react'
import { useChat } from '../contexts/ChatContext'
import { cn } from '@common/lib/utils'
import { Button } from '@common/components/Button'

interface Message {
    id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: number
    isStreaming?: boolean
}

interface SupportedFormat {
    label: string
    Icon: React.ComponentType<{ className?: string }>
    iconClassName: string
}

interface WebSearchLimits {
    minWebsites: number
    maxWebsites: number
}

interface RetrievalSourceSelectionRequest {
    requestId: string
    query: string
    availableSourceDomains: string[]
    defaultSelectedSourceDomains: string[]
}

const SUPPORTED_FORMATS: SupportedFormat[] = [
    { label: 'DOCX', Icon: FileText, iconClassName: 'text-sky-600' },
    { label: 'XLSX', Icon: FileSpreadsheet, iconClassName: 'text-emerald-600' },
    { label: 'PDF', Icon: FileText, iconClassName: 'text-rose-600' },
    { label: 'PPTX', Icon: Presentation, iconClassName: 'text-orange-600' },
    { label: 'TXT', Icon: FileText, iconClassName: 'text-zinc-600' },
    { label: 'MD', Icon: FileCode2, iconClassName: 'text-violet-600' },
    { label: 'CSV', Icon: FileSpreadsheet, iconClassName: 'text-teal-600' }
]

const DEFAULT_MIN_WEBSITES = 4
const DEFAULT_MAX_WEBSITES = 7
const MIN_WEBSITE_LIMIT = 0
const MAX_WEBSITE_LIMIT = 20

// Auto-scroll hook
const useAutoScroll = (messages: Message[]) => {
    const scrollRef = useRef<HTMLDivElement>(null)
    const prevCount = useRef(0)

    useLayoutEffect(() => {
        if (messages.length > prevCount.current) {
            setTimeout(() => {
                scrollRef.current?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'end'
                })
            }, 100)
        }
        prevCount.current = messages.length
    }, [messages.length])

    return scrollRef
}

// User Message Component - appears on the right
const UserMessage: React.FC<{ content: string }> = ({ content }) => (
    <div className="relative max-w-[85%] ml-auto animate-fade-in">
        <div className="bg-muted dark:bg-muted/50 rounded-3xl px-6 py-4">
            <div className="text-foreground" style={{ whiteSpace: 'pre-wrap' }}>
                {content}
            </div>
        </div>
    </div>
)

// Streaming Text Component
const StreamingText: React.FC<{ content: string }> = ({ content }) => {
    const [displayedContent, setDisplayedContent] = useState('')
    const [currentIndex, setCurrentIndex] = useState(0)

    useEffect(() => {
        if (currentIndex < content.length) {
            const timer = setTimeout(() => {
                setDisplayedContent(content.slice(0, currentIndex + 1))
                setCurrentIndex(currentIndex + 1)
            }, 10)
            return () => clearTimeout(timer)
        }

        return undefined
    }, [content, currentIndex])

    return (
        <div className="whitespace-pre-wrap text-foreground">
            {displayedContent}
            {currentIndex < content.length && (
                <span className="inline-block w-2 h-5 bg-primary/60 dark:bg-primary/40 ml-0.5 animate-pulse" />
            )}
        </div>
    )
}

// Markdown Renderer Component
const Markdown: React.FC<{ content: string }> = ({ content }) => (
    <div className="prose prose-sm dark:prose-invert max-w-none 
                    prose-headings:text-foreground prose-p:text-foreground 
                    prose-strong:text-foreground prose-ul:text-foreground 
                    prose-ol:text-foreground prose-li:text-foreground
                    prose-a:text-primary hover:prose-a:underline
                    prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 
                    prose-code:rounded prose-code:text-sm prose-code:text-foreground
                    prose-pre:bg-muted dark:prose-pre:bg-muted/50 prose-pre:p-3 
                    prose-pre:rounded-lg prose-pre:overflow-x-auto">
        <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={{
                // Custom code block styling
                code: ({ node, className, children, ...props }) => {
                    const inline = !className
                    return inline ? (
                        <code className="bg-muted dark:bg-muted/50 px-1 py-0.5 rounded text-sm text-foreground" {...props}>
                            {children}
                        </code>
                    ) : (
                        <code className={className} {...props}>
                            {children}
                        </code>
                    )
                },
                // Custom link styling
                a: ({ children, href }) => (
                    <a
                        href={href}
                        className="text-primary hover:underline"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        {children}
                    </a>
                ),
            }}
        >
            {content}
        </ReactMarkdown>
    </div>
)

// Assistant Message Component - appears on the left
const AssistantMessage: React.FC<{ content: string; isStreaming?: boolean }> = ({
    content,
    isStreaming
}) => (
    <div className="relative w-full animate-fade-in">
        <div className="py-1">
            {isStreaming ? (
                <StreamingText content={content} />
            ) : (
                <Markdown content={content} />
            )}
        </div>
    </div>
)

// Loading Indicator with spinning star
const LoadingIndicator: React.FC = () => {
    const [isVisible, setIsVisible] = useState(false)

    useEffect(() => {
        setIsVisible(true)
    }, [])

    return (
        <div className={cn(
            "transition-transform duration-300 ease-in-out",
            isVisible ? "scale-100" : "scale-0"
        )}>
            ...
        </div>
    )
}

const SupportedFormatsPanel: React.FC = () => (
    <div className="mt-3 rounded-2xl border border-border/70 bg-muted/40 px-3 py-3">
        <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Supported Formats
            </p>
            <p className="text-[11px] text-muted-foreground">
                Agent-created documents
            </p>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
            {SUPPORTED_FORMATS.map(({ label, Icon, iconClassName }) => (
                <div
                    key={label}
                    className="inline-flex items-center gap-2 rounded-full border border-border bg-background/90 px-3 py-1.5 text-xs font-medium text-foreground shadow-sm"
                >
                    <span className="inline-flex size-6 items-center justify-center rounded-full bg-muted">
                        <Icon className={cn('size-3.5', iconClassName)} />
                    </span>
                    <span>{label}</span>
                </div>
            ))}
        </div>
    </div>
)

// Chat Input Component with pill design
const ChatInput: React.FC<{
    onSend: (message: string, webSearchLimits: WebSearchLimits) => void
    disabled: boolean
    onResetVectorStore: () => void
}> = ({
    onSend,
    disabled,
    onResetVectorStore
}) => {
    const [value, setValue] = useState('')
    const [isFocused, setIsFocused] = useState(false)
    const [minWebsites, setMinWebsites] = useState(DEFAULT_MIN_WEBSITES)
    const [maxWebsites, setMaxWebsites] = useState(DEFAULT_MAX_WEBSITES)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto'
            const scrollHeight = textareaRef.current.scrollHeight
            const newHeight = Math.min(scrollHeight, 200) // Max 200px
            textareaRef.current.style.height = `${newHeight}px`
        }
    }, [value])

    const handleSubmit = () => {
        if (value.trim() && !disabled) {
            onSend(value.trim(), { minWebsites, maxWebsites })
            setValue('')
            // Reset textarea height
            if (textareaRef.current) {
                textareaRef.current.style.height = '24px'
            }
        }
    }

    const clampWebsiteLimit = (rawValue: number): number => {
        return Math.max(MIN_WEBSITE_LIMIT, Math.min(MAX_WEBSITE_LIMIT, rawValue))
    }

    const handleMinWebsitesChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const parsedValue = Number.parseInt(event.target.value, 10)
        if (Number.isNaN(parsedValue)) {
            return
        }

        const normalizedMin = clampWebsiteLimit(parsedValue)
        setMinWebsites(normalizedMin)
        setMaxWebsites((currentMax) => Math.max(currentMax, normalizedMin))
    }

    const handleMaxWebsitesChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const parsedValue = Number.parseInt(event.target.value, 10)
        if (Number.isNaN(parsedValue)) {
            return
        }

        const normalizedMax = clampWebsiteLimit(parsedValue)
        setMaxWebsites(Math.max(normalizedMax, minWebsites))
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSubmit()
        }
    }

    return (
        <div className={cn(
            "w-full border p-3 rounded-3xl bg-background dark:bg-secondary",
            "shadow-chat animate-spring-scale outline-none transition-all duration-200",
            isFocused ? "border-primary/20 dark:border-primary/30" : "border-border"
        )}>
            {/* Input Area */}
            <div className="w-full px-3 py-2">
                <div className="mb-3 rounded-2xl border border-border/70 bg-muted/30 px-3 py-2">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Web Search Limits
                    </p>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                            <span>Min websites</span>
                            <input
                                type="number"
                                value={minWebsites}
                                min={MIN_WEBSITE_LIMIT}
                                max={MAX_WEBSITE_LIMIT}
                                onChange={handleMinWebsitesChange}
                                className="h-8 rounded-xl border border-border bg-background px-2 text-xs text-foreground outline-none focus:border-primary/40"
                            />
                        </label>
                        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                            <span>Max websites</span>
                            <input
                                type="number"
                                value={maxWebsites}
                                min={minWebsites}
                                max={MAX_WEBSITE_LIMIT}
                                onChange={handleMaxWebsitesChange}
                                className="h-8 rounded-xl border border-border bg-background px-2 text-xs text-foreground outline-none focus:border-primary/40"
                            />
                        </label>
                    </div>
                </div>
                <div className="relative w-full overflow-hidden">
                    <textarea
                        ref={textareaRef}
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        onFocus={() => setIsFocused(true)}
                        onBlur={() => setIsFocused(false)}
                        onKeyDown={handleKeyDown}
                        placeholder="Send a message..."
                        className="w-full resize-none outline-none bg-transparent 
                                     text-foreground placeholder:text-muted-foreground
                                     min-h-[24px] max-h-[200px]"
                        rows={1}
                        style={{ lineHeight: '24px' }}
                    />
                </div>
            </div>

            {/* Send Button */}
            <div className="w-full flex items-center gap-1.5 px-1 mt-2 mb-1">
                <div className="flex-1" />
                <button
                    onClick={onResetVectorStore}
                    title="Empty vector store"
                    className={cn(
                        "h-9 rounded-full flex items-center gap-2 px-3 text-xs font-semibold",
                        "transition-all duration-200 border",
                        "border-border text-foreground",
                        "hover:bg-muted"
                    )}
                >
                    <Trash2 className="size-4" />
                    Reset vector store
                </button>
                <button
                    onClick={handleSubmit}
                    disabled={disabled || !value.trim()}
                    className={cn(
                        "size-9 rounded-full flex items-center justify-center",
                        "transition-all duration-200",
                        "bg-primary text-primary-foreground",
                        "hover:opacity-80 disabled:opacity-50"
                    )}
                >
                    <ArrowUp className="size-5" />
                </button>
            </div>

            <SupportedFormatsPanel />
        </div>
    )
}

// Conversation Turn Component
interface ConversationTurn {
    user?: Message
    assistant?: Message
}

const ConversationTurnComponent: React.FC<{
    turn: ConversationTurn
    isLoading?: boolean
}> = ({ turn, isLoading }) => (
    <div className="pt-12 flex flex-col gap-8">
        {turn.user && <UserMessage content={turn.user.content} />}
        {turn.assistant && (
            <AssistantMessage
                content={turn.assistant.content}
                isStreaming={turn.assistant.isStreaming}
            />
        )}
        {isLoading && (
            <div className="flex justify-start">
                <LoadingIndicator />
            </div>
        )}
    </div>
)

// Main Chat Component
export const Chat: React.FC = () => {
    const {
        messages,
        isLoading,
        sendMessage,
        clearChat,
        resetVectorStore,
        viewVectorStoreChunks
    } = useChat()
    const [retrievalSourceRequest, setRetrievalSourceRequest] =
        useState<RetrievalSourceSelectionRequest | null>(null)
    const [selectedRetrievalSourceDomains, setSelectedRetrievalSourceDomains] = useState<string[]>([])
    const scrollRef = useAutoScroll(messages)

    // Group messages into conversation turns
    const conversationTurns: ConversationTurn[] = []
    for (let i = 0; i < messages.length; i++) {
        if (messages[i].role === 'user') {
            const turn: ConversationTurn = { user: messages[i] }
            if (messages[i + 1]?.role === 'assistant') {
                turn.assistant = messages[i + 1]
                i++ // Skip next message since we've paired it
            }
            conversationTurns.push(turn)
        } else if (messages[i].role === 'assistant' &&
            (i === 0 || messages[i - 1]?.role !== 'user')) {
            // Handle standalone assistant messages
            conversationTurns.push({ assistant: messages[i] })
        }
    }

    // Check if we need to show loading after the last turn
    const showLoadingAfterLastTurn = isLoading &&
        messages[messages.length - 1]?.role === 'user'

    useEffect(() => {
        const handleRetrievalSourceSelectionRequest = (
            payload: RetrievalSourceSelectionRequest
        ) => {
            const availableSourceDomains = Array.isArray(payload.availableSourceDomains)
                ? payload.availableSourceDomains
                : []
            const defaultSelectedSourceDomains =
                Array.isArray(payload.defaultSelectedSourceDomains) &&
                payload.defaultSelectedSourceDomains.length > 0
                    ? payload.defaultSelectedSourceDomains
                    : availableSourceDomains

            setRetrievalSourceRequest({
                ...payload,
                availableSourceDomains,
                defaultSelectedSourceDomains
            })
            setSelectedRetrievalSourceDomains(defaultSelectedSourceDomains)
        }

        window.sidebarAPI.onRetrievalSourceSelectionRequest(
            handleRetrievalSourceSelectionRequest
        )

        return () => {
            window.sidebarAPI.removeRetrievalSourceSelectionRequestListener()
        }
    }, [])

    const toggleRetrievalSourceDomain = (domain: string) => {
        setSelectedRetrievalSourceDomains((currentDomains) =>
            currentDomains.includes(domain)
                ? currentDomains.filter((currentDomain) => currentDomain !== domain)
                : [...currentDomains, domain]
        )
    }

    const submitRetrievalSourceSelection = (action: 'confirm' | 'cancel') => {
        if (!retrievalSourceRequest) {
            return
        }

        window.sidebarAPI.respondToRetrievalSourceSelection({
            requestId: retrievalSourceRequest.requestId,
            action,
            selectedSourceDomains:
                action === 'confirm' ? selectedRetrievalSourceDomains : []
        })
        setRetrievalSourceRequest(null)
        setSelectedRetrievalSourceDomains([])
    }

    const availableRetrievalSourceDomains =
        retrievalSourceRequest?.availableSourceDomains ?? []
    const canConfirmRetrievalSourceSelection =
        availableRetrievalSourceDomains.length === 0 ||
        selectedRetrievalSourceDomains.length > 0

    return (
        <div className="relative flex flex-col h-full bg-background">
            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto">
                <div className="h-8 max-w-3xl mx-auto px-4">
                    {/* New Chat Button - Floating */}
                    {messages.length > 0 && (
                        <Button
                            onClick={clearChat}
                            title="Start new chat"
                            variant="ghost"
                        >
                            <Plus className="size-4" />
                            New Chat
                        </Button>
                    )}
                </div>

                <div className="pb-4 relative max-w-3xl mx-auto px-4">

                    {messages.length === 0 ? (
                        // Empty State
                        <div className="flex items-center justify-center h-full min-h-[400px]">
                            <div className="text-center animate-fade-in max-w-md mx-auto gap-2 flex flex-col">
                                <h3 className="text-2xl font-bold">🫐</h3>
                                <p className="text-muted-foreground text-sm">
                                    Press ⌘E to toggle the sidebar
                                </p>
                            </div>
                        </div>
                    ) : (
                        <>

                            {/* Render conversation turns */}
                            {conversationTurns.map((turn, index) => (
                                <ConversationTurnComponent
                                    key={`turn-${index}`}
                                    turn={turn}
                                    isLoading={
                                        showLoadingAfterLastTurn &&
                                        index === conversationTurns.length - 1
                                    }
                                />
                            ))}
                        </>
                    )}

                    {/* Scroll anchor */}
                    <div ref={scrollRef} />
                </div>
            </div>

            {/* Input Area */}
            <div className="p-4 pt-2">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                    <button
                        onClick={() => void viewVectorStoreChunks()}
                        title="Open vector store chunk viewer"
                        className={cn(
                            "h-9 rounded-full flex items-center gap-2 px-3 text-xs font-semibold",
                            "transition-all duration-200 border",
                            "border-border text-foreground",
                            "hover:bg-muted disabled:opacity-60"
                        )}
                        disabled={isLoading}
                    >
                        <Database className="size-4" />
                        View vector chunks
                    </button>
                </div>
                <ChatInput
                    onSend={sendMessage}
                    disabled={isLoading}
                    onResetVectorStore={resetVectorStore}
                />
            </div>

            {retrievalSourceRequest && (
                <div className="absolute inset-0 z-30 flex items-end justify-center bg-background/55 px-4 py-5 backdrop-blur-sm md:items-center">
                    <div className="w-full max-w-md rounded-[28px] border border-border/80 bg-background/95 p-4 shadow-2xl">
                        <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start gap-3">
                                <div className="mt-0.5 inline-flex size-10 items-center justify-center rounded-2xl bg-sky-500/10 text-sky-600">
                                    <ListFilter className="size-5" />
                                </div>
                                <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                        Retrieval Sources
                                    </p>
                                    <h3 className="mt-1 text-sm font-semibold text-foreground">
                                        Select source domains before vector retrieval
                                    </h3>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => submitRetrievalSourceSelection('cancel')}
                                className="inline-flex size-8 items-center justify-center rounded-full border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                                title="Cancel retrieval"
                            >
                                <X className="size-4" />
                            </button>
                        </div>

                        <div className="mt-4 rounded-2xl border border-border/70 bg-muted/30 px-3 py-3">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                Retrieval Query
                            </p>
                            <p className="mt-2 text-sm leading-6 text-foreground">
                                {retrievalSourceRequest.query || 'Retrieve the most relevant indexed chunks.'}
                            </p>
                        </div>

                        <div className="mt-4 flex items-center justify-between gap-2">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                Source Domains
                            </p>
                            {availableRetrievalSourceDomains.length > 0 && (
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setSelectedRetrievalSourceDomains(
                                                availableRetrievalSourceDomains
                                            )
                                        }
                                        className="text-[11px] font-semibold text-sky-600 transition-colors hover:text-sky-500"
                                    >
                                        Select all
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setSelectedRetrievalSourceDomains([])}
                                        className="text-[11px] font-semibold text-muted-foreground transition-colors hover:text-foreground"
                                    >
                                        Clear
                                    </button>
                                </div>
                            )}
                        </div>

                        {availableRetrievalSourceDomains.length > 0 ? (
                            <div className="mt-3 grid max-h-72 gap-2 overflow-y-auto pr-1">
                                {availableRetrievalSourceDomains.map((domain) => {
                                    const isSelected =
                                        selectedRetrievalSourceDomains.includes(domain)

                                    return (
                                        <button
                                            key={domain}
                                            type="button"
                                            onClick={() => toggleRetrievalSourceDomain(domain)}
                                            className={cn(
                                                'flex items-center justify-between gap-3 rounded-2xl border px-3 py-3 text-left transition-all duration-200',
                                                isSelected
                                                    ? 'border-sky-400/70 bg-sky-500/10 shadow-sm'
                                                    : 'border-border bg-background hover:border-sky-300/60 hover:bg-muted/60'
                                            )}
                                        >
                                            <div className="min-w-0">
                                                <p className="truncate text-sm font-medium text-foreground">
                                                    {domain}
                                                </p>
                                                <p className="mt-1 text-xs text-muted-foreground">
                                                    Include chunks from this domain in retrieval.
                                                </p>
                                            </div>
                                            <div
                                                className={cn(
                                                    'inline-flex size-6 shrink-0 items-center justify-center rounded-full border',
                                                    isSelected
                                                        ? 'border-sky-500 bg-sky-500 text-white'
                                                        : 'border-border bg-background text-transparent'
                                                )}
                                            >
                                                <Check className="size-3.5" />
                                            </div>
                                        </button>
                                    )
                                })}
                            </div>
                        ) : (
                            <div className="mt-3 rounded-2xl border border-dashed border-border bg-muted/20 px-3 py-4">
                                <div className="flex items-start gap-3">
                                    <div className="inline-flex size-9 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                                        <Globe className="size-4" />
                                    </div>
                                    <div>
                                        <p className="text-sm font-medium text-foreground">
                                            No indexed source domains found
                                        </p>
                                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                            Retrieval can continue, but there is no source-domain filter to apply yet.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl bg-muted/20 px-3 py-3">
                            <div>
                                <p className="text-xs font-semibold text-foreground">
                                    {availableRetrievalSourceDomains.length > 0
                                        ? `${selectedRetrievalSourceDomains.length} of ${availableRetrievalSourceDomains.length} sources selected`
                                        : 'No source filter available'}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">
                                    Retrieval will run 3 queries, take top 5 chunks per query, then merge the best 12.
                                </p>
                            </div>
                        </div>

                        <div className="mt-4 flex items-center justify-end gap-2">
                            <button
                                type="button"
                                onClick={() => submitRetrievalSourceSelection('cancel')}
                                className="h-10 rounded-full border border-border px-4 text-xs font-semibold text-foreground transition-colors hover:bg-muted"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={() => submitRetrievalSourceSelection('confirm')}
                                disabled={!canConfirmRetrievalSourceSelection}
                                className={cn(
                                    'h-10 rounded-full px-4 text-xs font-semibold transition-all duration-200',
                                    'bg-primary text-primary-foreground',
                                    'hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
                                )}
                            >
                                {availableRetrievalSourceDomains.length > 0
                                    ? `Retrieve from ${selectedRetrievalSourceDomains.length} source${selectedRetrievalSourceDomains.length === 1 ? '' : 's'}`
                                    : 'Continue retrieval'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
