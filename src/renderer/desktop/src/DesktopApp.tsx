import React, { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import {
    ArrowLeft,
    BadgeCheck,
    ChevronRight,
    File,
    FilePlus2,
    FileArchive,
    FileCode2,
    FileImage,
    FileText,
    Folder,
    FolderPlus,
    FolderOpen,
    HardDrive,
    House,
    MessageSquare,
    Monitor,
    MousePointer2,
    RefreshCcw,
    Send,
    Sparkles
} from 'lucide-react'
import { cn } from '@common/lib/utils'

interface DesktopEntry {
    name: string
    path: string
    kind: 'directory' | 'file'
    extension: string
}

interface DesktopBreadcrumb {
    name: string
    path: string
}

interface DesktopDirectoryData {
    desktopPath: string
    currentPath: string
    parentPath: string | null
    breadcrumbs: DesktopBreadcrumb[]
    entries: DesktopEntry[]
}

interface CursorWave {
    id: number
    x: number
    y: number
}

type DesktopCursorTarget =
    | 'desktop-center'
    | 'folder-grid'
    | 'inspector-panel'
    | 'header-controls'
    | 'taskbar'
    | 'current-folder-card'
    | 'files-end'

type DesktopCursorAction =
    | 'move_cursor'
    | 'click_folder'
    | 'move_to_folder'
    | 'show_folder'
    | 'move_to_file'
    | 'read_file'

interface AgentCursorMovePayload {
    eventId?: string
    action?: DesktopCursorAction
    target: DesktopCursorTarget
    reason: string
    click?: boolean
    label?: string
    loading?: boolean
    path?: string
    navigate?: boolean
}

interface FileConfirmationRequest {
    requestId: string
    toolName: string
    path: string
    message: string
}

interface DesktopActionToastPayload {
    kind?: 'folder' | 'file' | 'update' | 'conversion' | 'batch'
    title: string
    description?: string
    path?: string
}

interface DesktopActionFeedbackPayload {
    clearCursor?: boolean
    notifications?: DesktopActionToastPayload[]
}

interface DesktopActionToast extends DesktopActionToastPayload {
    id: string
}

interface DesktopChatMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
}

const normalizeDesktopChatMessages = (rawMessages: any[]): DesktopChatMessage[] =>
    rawMessages.flatMap((message: any, index: number) => {
        if (!message || (message.role !== 'user' && message.role !== 'assistant')) {
            return []
        }

        if (typeof message.content === 'string') {
            const content = message.content.trim()
            return content
                ? [{
                    id: `desktop-chat-${index}`,
                    role: message.role,
                    content
                }]
                : []
        }

        if (!Array.isArray(message.content)) {
            return []
        }

        const textContent = message.content
            .filter(
                (part: any) =>
                    part &&
                    typeof part === 'object' &&
                    part.type === 'text' &&
                    typeof part.text === 'string'
            )
            .map((part: { text: string }) => part.text)
            .join('\n')
            .trim()

        return textContent
            ? [{
                id: `desktop-chat-${index}`,
                role: message.role,
                content: textContent
            }]
            : []
    })

const getEntryVisual = (entry: DesktopEntry) => {
    if (entry.kind === 'directory') {
        return {
            Icon: Folder,
            accent: 'text-sky-100',
            badge: 'Folder'
        }
    }

    const extension = entry.extension.toLowerCase()
    const imageExtensions = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'])
    const archiveExtensions = new Set(['zip', 'rar', '7z', 'tar', 'gz'])
    const codeExtensions = new Set(['js', 'ts', 'tsx', 'jsx', 'json', 'html', 'css', 'py', 'java', 'cpp', 'cs'])
    const documentExtensions = new Set(['txt', 'md', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'])

    if (imageExtensions.has(extension)) {
        return {
            Icon: FileImage,
            accent: 'text-emerald-100',
            badge: extension.toUpperCase()
        }
    }

    if (archiveExtensions.has(extension)) {
        return {
            Icon: FileArchive,
            accent: 'text-amber-100',
            badge: extension.toUpperCase()
        }
    }

    if (codeExtensions.has(extension)) {
        return {
            Icon: FileCode2,
            accent: 'text-violet-100',
            badge: extension.toUpperCase()
        }
    }

    if (documentExtensions.has(extension)) {
        return {
            Icon: FileText,
            accent: 'text-cyan-100',
            badge: extension ? extension.toUpperCase() : 'FILE'
        }
    }

    return {
        Icon: File,
        accent: 'text-slate-100',
        badge: extension ? extension.toUpperCase() : 'FILE'
    }
}

const getToastVisual = (kind?: DesktopActionToastPayload['kind']) => {
    switch (kind) {
        case 'folder':
            return {
                Icon: FolderPlus,
                iconClassName: 'text-sky-100',
                iconSurfaceClassName: 'bg-sky-300/16'
            }
        case 'conversion':
            return {
                Icon: RefreshCcw,
                iconClassName: 'text-amber-100',
                iconSurfaceClassName: 'bg-amber-300/16'
            }
        case 'update':
            return {
                Icon: BadgeCheck,
                iconClassName: 'text-emerald-100',
                iconSurfaceClassName: 'bg-emerald-300/16'
            }
        case 'batch':
            return {
                Icon: FilePlus2,
                iconClassName: 'text-violet-100',
                iconSurfaceClassName: 'bg-violet-300/16'
            }
        case 'file':
        default:
            return {
                Icon: FilePlus2,
                iconClassName: 'text-cyan-100',
                iconSurfaceClassName: 'bg-cyan-300/16'
            }
    }
}

const DesktopIcon: React.FC<{
    entry: DesktopEntry
    isActive: boolean
    onActivate: (entry: DesktopEntry) => void | Promise<void>
    onPreview: (entry: DesktopEntry) => void
    buttonRef?: (node: HTMLButtonElement | null) => void
}> = ({ entry, isActive, onActivate, onPreview, buttonRef }) => {
    const { Icon, accent, badge } = getEntryVisual(entry)

    return (
        <button
            ref={buttonRef}
            type="button"
            onClick={() => {
                void onActivate(entry)
            }}
            onMouseEnter={() => onPreview(entry)}
            onFocus={() => onPreview(entry)}
            className={cn(
                'group flex w-[116px] flex-col items-center rounded-3xl px-2 py-3 text-center transition-all duration-150',
                'hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-sky-300/70',
                isActive && 'bg-sky-300/18 shadow-[0_18px_40px_rgba(8,17,32,0.38)]'
            )}
            title={entry.name}
        >
            <div className="relative mb-3">
                <div className="absolute inset-0 rounded-[22px] bg-sky-300/20 blur-md transition-opacity duration-200 group-hover:opacity-100" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-[22px] border border-white/15 bg-white/10 backdrop-blur-md">
                    <Icon className={cn('size-8 drop-shadow-[0_8px_18px_rgba(8,17,32,0.38)]', accent)} />
                </div>
            </div>

            <span className="max-h-10 overflow-hidden text-xs font-medium leading-5 text-slate-50 [word-break:break-word]">
                {entry.name}
            </span>
            <span className="mt-1 rounded-full border border-white/10 bg-black/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-200/70">
                {badge}
            </span>
        </button>
    )
}

export const DesktopApp: React.FC = () => {
    const rootRef = useRef<HTMLDivElement>(null)
    const iconFieldRef = useRef<HTMLDivElement>(null)
    const entryRefs = useRef(new Map<string, HTMLButtonElement>())
    const breadcrumbRefs = useRef(new Map<string, HTMLButtonElement>())
    const desktopRootButtonRef = useRef<HTMLButtonElement>(null)
    const upOneLevelButtonRef = useRef<HTMLButtonElement>(null)
    const [desktopPath, setDesktopPath] = useState('')
    const [currentPath, setCurrentPath] = useState('')
    const [parentPath, setParentPath] = useState<string | null>(null)
    const [breadcrumbs, setBreadcrumbs] = useState<DesktopBreadcrumb[]>([])
    const [entries, setEntries] = useState<DesktopEntry[]>([])
    const [activeEntryPath, setActiveEntryPath] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [now, setNow] = useState(() => new Date())
    const [cursorVisible, setCursorVisible] = useState(false)
    const [cursorPressed, setCursorPressed] = useState(false)
    const [cursorLabel, setCursorLabel] = useState<string | null>(null)
    const [cursorDescription, setCursorDescription] = useState<string | null>(null)
    const [cursorLoading, setCursorLoading] = useState(false)
    const [cursorWaves, setCursorWaves] = useState<CursorWave[]>([])
    const [pendingConfirmation, setPendingConfirmation] = useState<FileConfirmationRequest | null>(null)
    const [actionToasts, setActionToasts] = useState<DesktopActionToast[]>([])
    const [chatMessages, setChatMessages] = useState<DesktopChatMessage[]>([])
    const [chatDraft, setChatDraft] = useState('')
    const [isSendingChat, setIsSendingChat] = useState(false)
    const cursorRef = useRef<HTMLDivElement>(null)
    const conversationScrollRef = useRef<HTMLDivElement>(null)
    const cursorPointRef = useRef({ x: 160, y: 160 })
    const cursorSequenceRef = useRef<Promise<void>>(Promise.resolve())
    const loadDirectoryRef = useRef<(directoryPath?: string) => Promise<DesktopDirectoryData>>(async () => ({
        desktopPath: desktopPathRef.current,
        currentPath: currentPathRef.current,
        parentPath: parentPathRef.current,
        breadcrumbs: breadcrumbsRef.current,
        entries: entriesRef.current
    }))
    const animateCursorMoveRef = useRef<(payload: AgentCursorMovePayload) => Promise<void>>(async () => {})
    const desktopPathRef = useRef('')
    const currentPathRef = useRef('')
    const parentPathRef = useRef<string | null>(null)
    const breadcrumbsRef = useRef<DesktopBreadcrumb[]>([])
    const entriesRef = useRef<DesktopEntry[]>([])
    const activeEntryPathRef = useRef<string | null>(null)
    const cursorLabelTimeoutRef = useRef<number | null>(null)
    const cursorLoadingSafetyTimeoutRef = useRef<number | null>(null)
    const actionToastTimeoutsRef = useRef(new Map<string, number>())
    const activeCursorMovesRef = useRef(0)
    const pendingCursorClearRef = useRef(false)
    const pendingCursorClearDelayRef = useRef(900)
    const waveIdRef = useRef(0)

    const logDesktopDebug = useCallback((event: string, details: Record<string, unknown> = {}) => {
        window.desktopAPI.logDebug(event, {
            ...details,
            currentPath: currentPathRef.current || null,
            parentPath: parentPathRef.current || null,
            breadcrumbTail: breadcrumbsRef.current[breadcrumbsRef.current.length - 1]?.path || null,
            activeEntryPath: activeEntryPathRef.current || null
        })
    }, [])

    const activeEntry = entries.find((entry) => entry.path === activeEntryPath) || null
    const folderCount = entries.filter((entry) => entry.kind === 'directory').length
    const fileCount = entries.length - folderCount

    const clearCursorBadgeTimeout = useCallback(() => {
        if (cursorLabelTimeoutRef.current) {
            window.clearTimeout(cursorLabelTimeoutRef.current)
            cursorLabelTimeoutRef.current = null
        }
    }, [])

    const clearCursorLoadingSafetyTimeout = useCallback(() => {
        if (cursorLoadingSafetyTimeoutRef.current) {
            window.clearTimeout(cursorLoadingSafetyTimeoutRef.current)
            cursorLoadingSafetyTimeoutRef.current = null
        }
    }, [])

    const scheduleCursorBadgeHide = useCallback((delayMs: number) => {
        clearCursorBadgeTimeout()
        cursorLabelTimeoutRef.current = window.setTimeout(() => {
            setCursorLabel(null)
            setCursorDescription(null)
            setCursorLoading(false)
        }, delayMs)
    }, [clearCursorBadgeTimeout])

    const applyPendingCursorClear = useCallback((delayMs?: number) => {
        if (!pendingCursorClearRef.current && delayMs === undefined) {
            return
        }
        pendingCursorClearRef.current = false
        setCursorLoading(false)
        scheduleCursorBadgeHide(delayMs ?? pendingCursorClearDelayRef.current)
    }, [scheduleCursorBadgeHide])

    const dismissActionToast = useCallback((toastId: string) => {
        const timeoutId = actionToastTimeoutsRef.current.get(toastId)
        if (timeoutId) {
            window.clearTimeout(timeoutId)
            actionToastTimeoutsRef.current.delete(toastId)
        }
        setActionToasts((current) => current.filter((toast) => toast.id !== toastId))
    }, [])

    const pushActionToast = useCallback((payload: DesktopActionToastPayload) => {
        if (!payload.title.trim()) {
            return
        }

        const toastId = `desktop-toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const nextToast: DesktopActionToast = {
            id: toastId,
            ...payload
        }

        setActionToasts((current) => [...current, nextToast].slice(-4))
        const timeoutId = window.setTimeout(() => {
            dismissActionToast(toastId)
        }, 5200)
        actionToastTimeoutsRef.current.set(toastId, timeoutId)
    }, [dismissActionToast])

    const applyDesktopActionFeedback = useCallback((payload?: DesktopActionFeedbackPayload) => {
        const notifications = Array.isArray(payload?.notifications)
            ? payload.notifications.filter(
                (notification): notification is DesktopActionToastPayload =>
                    !!notification &&
                    typeof notification.title === 'string' &&
                    notification.title.trim().length > 0
            )
            : []

        notifications.forEach((notification) => pushActionToast(notification))

        if (notifications.length > 0) {
            setCursorLabel(notifications[0].title)
            setCursorDescription(notifications[0].description ?? null)
        }

        if (payload?.clearCursor !== false) {
            pendingCursorClearRef.current = true
            pendingCursorClearDelayRef.current = notifications.length > 0 ? 2200 : 900
            if (activeCursorMovesRef.current === 0) {
                applyPendingCursorClear()
            }
        }
    }, [applyPendingCursorClear, pushActionToast])

    const applyDirectoryData = useCallback((data: DesktopDirectoryData) => {
        desktopPathRef.current = data.desktopPath
        currentPathRef.current = data.currentPath
        parentPathRef.current = data.parentPath
        breadcrumbsRef.current = data.breadcrumbs
        entriesRef.current = data.entries

        flushSync(() => {
            setDesktopPath(data.desktopPath)
            setCurrentPath(data.currentPath)
            setParentPath(data.parentPath)
            setBreadcrumbs(data.breadcrumbs)
            setEntries(data.entries)
            setActiveEntryPath((current) =>
                current && data.entries.some((entry) => entry.path === current)
                    ? current
                    : null
            )
        })
    }, [])

    const loadDirectory = useCallback(async (directoryPath?: string): Promise<DesktopDirectoryData> => {
        setIsLoading(true)
        setError(null)
        logDesktopDebug('load_directory_start', {
            requestedPath: directoryPath ?? null
        })

        try {
            const data = await window.desktopAPI.getDesktopEntries(directoryPath)
            applyDirectoryData(data)
            logDesktopDebug('load_directory_result', {
                requestedPath: directoryPath ?? null,
                loadedPath: data.currentPath,
                entryCount: data.entries.length,
                entriesPreview: data.entries.slice(0, 8).map((entry) => ({
                    name: entry.name,
                    kind: entry.kind
                }))
            })
            return data
        } catch (loadError) {
            console.error('Failed to load desktop entries:', loadError)
            setError('Unable to read the contents of this desktop folder.')
            logDesktopDebug('load_directory_error', {
                requestedPath: directoryPath ?? null,
                error: loadError instanceof Error
                    ? { message: loadError.message, stack: loadError.stack }
                    : String(loadError)
            })
            const fallbackData = {
                desktopPath: desktopPathRef.current,
                currentPath: currentPathRef.current,
                parentPath: parentPathRef.current,
                breadcrumbs: breadcrumbsRef.current,
                entries: entriesRef.current
            }
            return fallbackData
        } finally {
            setIsLoading(false)
        }
    }, [applyDirectoryData, logDesktopDebug])

    const openFile = useCallback(async (entry: DesktopEntry) => {
        try {
            const didOpen = await window.desktopAPI.openDesktopFile(entry.path)
            if (!didOpen) {
                setError(`Unable to open "${entry.name}".`)
            }
        } catch (openError) {
            console.error('Failed to open desktop file:', openError)
            setError(`Unable to open "${entry.name}".`)
        }
    }, [])

    const activateEntry = useCallback(async (entry: DesktopEntry) => {
        setActiveEntryPath(entry.path)
        logDesktopDebug('activate_entry', {
            entryPath: entry.path,
            entryName: entry.name,
            entryKind: entry.kind
        })

        if (entry.kind === 'directory') {
            await loadDirectory(entry.path)
            return
        }

        await openFile(entry)
    }, [loadDirectory, logDesktopDebug, openFile])

    useEffect(() => {
        void loadDirectory()
    }, [loadDirectory])

    useEffect(() => {
        desktopPathRef.current = desktopPath
    }, [desktopPath])

    useEffect(() => {
        loadDirectoryRef.current = loadDirectory
    }, [loadDirectory])

    useEffect(() => {
        currentPathRef.current = currentPath
        if (currentPath) {
            logDesktopDebug('current_path_updated', {
                currentPath,
                entryCount: entriesRef.current.length,
                entriesPreview: entriesRef.current.slice(0, 8).map((entry) => ({
                    name: entry.name,
                    kind: entry.kind
                }))
            })
        }
    }, [currentPath, logDesktopDebug])

    useEffect(() => {
        parentPathRef.current = parentPath
    }, [parentPath])

    useEffect(() => {
        breadcrumbsRef.current = breadcrumbs
    }, [breadcrumbs])

    useEffect(() => {
        entriesRef.current = entries
    }, [entries])

    useEffect(() => {
        activeEntryPathRef.current = activeEntryPath
    }, [activeEntryPath])

    const updateCursorPosition = (clientX: number, clientY: number) => {
        cursorPointRef.current = { x: clientX, y: clientY }
        if (!cursorRef.current) return
        cursorRef.current.style.transform = `translate(${clientX}px, ${clientY}px)`
    }

    const waitForUi = (delayMs = 140) =>
        new Promise<void>((resolve) => {
            window.setTimeout(resolve, delayMs)
        })

    const normalizePath = (value: string) => value.replace(/[\\/]+/g, '\\').toLowerCase()
    const desktopRootFolderAlias = 'BLUEBERRY'
    const desktopRootFolderCanonical = 'BLUEBARRY'

    const joinWindowsPath = (base: string, segment: string) => {
        const trimmedBase = base.replace(/[\\/]+$/, '')
        return `${trimmedBase}\\${segment}`
    }

    const getPathLeafName = (value: string) => {
        const normalized = value.replace(/[\\/]+$/, '')
        const segments = normalized.split(/[\\/]+/).filter(Boolean)
        return segments[segments.length - 1] ?? normalized
    }

    const getParentDirectoryPath = (value: string) => {
        const normalized = value.replace(/[\\/]+$/, '')
        const separatorIndex = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'))
        if (separatorIndex < 0) {
            return normalized
        }

        const parentPath = normalized.slice(0, separatorIndex)
        return /^[A-Za-z]:$/.test(parentPath) ? `${parentPath}\\` : parentPath
    }

    const waitForDirectoryPath = useCallback((expectedPath: string, timeoutMs = 2200) => {
        const normalizedExpectedPath = normalizePath(expectedPath)

        return new Promise<boolean>((resolve) => {
            const startedAt = Date.now()

            const check = () => {
                const currentPathMatches =
                    normalizePath(currentPathRef.current || '') === normalizedExpectedPath
                const breadcrumbPathMatches =
                    normalizePath(breadcrumbsRef.current[breadcrumbsRef.current.length - 1]?.path || '')
                    === normalizedExpectedPath

                if (currentPathMatches && breadcrumbPathMatches) {
                    logDesktopDebug('wait_for_directory_path_success', {
                        expectedPath,
                        timeoutMs,
                        elapsedMs: Date.now() - startedAt
                    })
                    resolve(true)
                    return
                }

                if (Date.now() - startedAt >= timeoutMs) {
                    logDesktopDebug('wait_for_directory_path_timeout', {
                        expectedPath,
                        timeoutMs,
                        elapsedMs: Date.now() - startedAt
                    })
                    resolve(false)
                    return
                }

                window.setTimeout(check, 24)
            }

            check()
        })
    }, [logDesktopDebug])

    const waitForEntryButton = useCallback((entryPath: string, timeoutMs = 2200) => {
        const normalizedEntryPath = normalizePath(entryPath)

        return new Promise<HTMLButtonElement | null>((resolve) => {
            const startedAt = Date.now()

            const check = () => {
                const matchingEntry = Array.from(entryRefs.current.entries()).find(
                    ([path]) => normalizePath(path) === normalizedEntryPath
                )

                if (matchingEntry?.[1]) {
                    resolve(matchingEntry[1])
                    return
                }

                if (Date.now() - startedAt >= timeoutMs) {
                    resolve(null)
                    return
                }

                window.setTimeout(check, 24)
            }

            check()
        })
    }, [])

    const relativeSegments = (rootPath: string, targetPath: string) => {
        const normalizedRoot = rootPath.replace(/[\\/]+$/, '')
        const normalizedTarget = targetPath.replace(/[\\/]+$/, '')
        const relativePath = normalizedTarget
            .slice(normalizedRoot.length)
            .replace(/^[\\/]+/, '')

        return relativePath.split(/[\\/]+/).filter(Boolean)
    }

    const buildPathFromSegments = (rootPath: string, segments: string[]) =>
        segments.reduce((currentPath, segment) => joinWindowsPath(currentPath, segment), rootPath)

    const getSharedPrefixLength = (left: string[], right: string[]) => {
        const maxLength = Math.min(left.length, right.length)
        let index = 0

        while (index < maxLength && left[index].toLowerCase() === right[index].toLowerCase()) {
            index += 1
        }

        return index
    }

    const coercePathToDesktopRoot = (value: string) => {
        const desktopRoot = desktopPathRef.current
        if (!desktopRoot) {
            return value
        }

        const normalizedDesktopRoot = normalizePath(desktopRoot).replace(/[\\/]+$/, '')
        const normalizedValue = normalizePath(value).replace(/[\\/]+$/, '')
        if (
            normalizedValue === normalizedDesktopRoot
            || normalizedValue.startsWith(`${normalizedDesktopRoot}\\`)
        ) {
            return value
        }

        if (getPathLeafName(desktopRoot).toLowerCase() !== desktopRootFolderCanonical.toLowerCase()) {
            return value
        }

        const aliasRoot = joinWindowsPath(
            getParentDirectoryPath(desktopRoot),
            desktopRootFolderAlias
        )
        const normalizedAliasRoot = normalizePath(aliasRoot).replace(/[\\/]+$/, '')
        if (
            normalizedValue !== normalizedAliasRoot
            && !normalizedValue.startsWith(`${normalizedAliasRoot}\\`)
        ) {
            return value
        }

        const suffixSegments = relativeSegments(aliasRoot, value)
        return buildPathFromSegments(desktopRoot, suffixSegments)
    }

    const registerEntryRef = useCallback((path: string, node: HTMLButtonElement | null) => {
        if (node) {
            entryRefs.current.set(path, node)
            return
        }

        entryRefs.current.delete(path)
    }, [])

    const registerBreadcrumbRef = useCallback((path: string, node: HTMLButtonElement | null) => {
        if (node) {
            breadcrumbRefs.current.set(path, node)
            return
        }

        breadcrumbRefs.current.delete(path)
    }, [])

    const getNodePoint = useCallback((node: HTMLElement | null) => {
        const rootRect = rootRef.current?.getBoundingClientRect()
        if (!rootRect || !node) {
            return null
        }

        const rect = node.getBoundingClientRect()
        return {
            x: rect.left - rootRect.left + rect.width / 2,
            y: rect.top - rootRect.top + rect.height / 2
        }
    }, [])

    const getEntryPoint = useCallback((entryPath: string) => {
        const entryNode = entryRefs.current.get(entryPath)
        return getNodePoint(entryNode ?? null)
    }, [getNodePoint])

    const getCursorTargetPoint = useCallback((target: DesktopCursorTarget) => {
        const viewportWidth = rootRef.current?.clientWidth ?? window.innerWidth
        const viewportHeight = rootRef.current?.clientHeight ?? window.innerHeight

        if (target === 'files-end') {
            const iconField = iconFieldRef.current
            if (iconField) {
                const lastIcon = iconField.lastElementChild as HTMLElement | null
                if (lastIcon) {
                    const iconRect = lastIcon.getBoundingClientRect()
                    const fieldRect = iconField.getBoundingClientRect()
                    const rootRect = rootRef.current?.getBoundingClientRect()
                    const slotHeight = iconRect.height + 14
                    const slotWidth = iconRect.width + 12
                    const hasRoomBelow = iconRect.bottom + slotHeight <= fieldRect.bottom
                    const nextViewportX = hasRoomBelow ? iconRect.left + iconRect.width / 2 : iconRect.left + slotWidth
                    const nextViewportY = hasRoomBelow ? iconRect.bottom + 14 + iconRect.height / 2 : fieldRect.top + iconRect.height / 2
                    return {
                        x: rootRect ? nextViewportX - rootRect.left : nextViewportX,
                        y: rootRect ? nextViewportY - rootRect.top : nextViewportY
                    }
                }

                const fieldRect = iconField.getBoundingClientRect()
                const rootRect = rootRef.current?.getBoundingClientRect()
                return {
                    x: rootRect ? fieldRect.left - rootRect.left + 72 : fieldRect.left + 72,
                    y: rootRect ? fieldRect.top - rootRect.top + 72 : fieldRect.top + 72
                }
            }
        }

        const pointMap: Record<DesktopCursorTarget, { x: number; y: number }> = {
            'desktop-center': { x: viewportWidth * 0.48, y: viewportHeight * 0.48 },
            'folder-grid': { x: viewportWidth * 0.3, y: viewportHeight * 0.5 },
            'inspector-panel': { x: viewportWidth * 0.84, y: viewportHeight * 0.38 },
            'header-controls': { x: viewportWidth * 0.82, y: viewportHeight * 0.12 },
            'taskbar': { x: viewportWidth * 0.5, y: viewportHeight * 0.93 },
            'current-folder-card': { x: viewportWidth * 0.24, y: viewportHeight * 0.28 },
            'files-end': { x: viewportWidth * 0.34, y: viewportHeight * 0.54 }
        }

        return pointMap[target] ?? pointMap['desktop-center']
    }, [])

    const createCursorWave = (clientX: number, clientY: number) => {
        const id = waveIdRef.current++
        setCursorWaves((current) => [...current, { id, x: clientX, y: clientY }])

        window.setTimeout(() => {
            setCursorWaves((current) => current.filter((wave) => wave.id !== id))
        }, 560)
    }

    const animateCursorToPoint = useCallback((destination: { x: number; y: number }, payload: AgentCursorMovePayload) => {
        const start = cursorPointRef.current
        const durationMs = 560
        const animationStart = performance.now()
        const nextLabel = payload.label ?? payload.reason
        const nextDescription =
            payload.label && payload.reason.trim() && payload.reason !== payload.label
                ? payload.reason
                : null

        setCursorVisible(true)
        setCursorPressed(false)
        setCursorLabel(nextLabel)
        setCursorDescription(nextDescription)
        setCursorLoading(payload.loading === true)

        if (payload.loading === true) {
            clearCursorBadgeTimeout()
            clearCursorLoadingSafetyTimeout()
            cursorLoadingSafetyTimeoutRef.current = window.setTimeout(() => {
                setCursorLoading(false)
                scheduleCursorBadgeHide(900)
            }, 12000)
        } else {
            clearCursorLoadingSafetyTimeout()
            scheduleCursorBadgeHide(nextDescription ? 4200 : 2400)
        }

        return new Promise<void>((resolve) => {
            const step = (timestamp: number) => {
                const progress = Math.min((timestamp - animationStart) / durationMs, 1)
                const eased = 1 - Math.pow(1 - progress, 3)
                const nextX = start.x + (destination.x - start.x) * eased
                const nextY = start.y + (destination.y - start.y) * eased
                updateCursorPosition(nextX, nextY)

                if (progress < 1) {
                    window.requestAnimationFrame(step)
                    return
                }

                if (payload.click) {
                    setCursorPressed(true)
                    createCursorWave(destination.x, destination.y)
                    window.setTimeout(() => setCursorPressed(false), 180)
                }

                window.setTimeout(() => resolve(), payload.click ? 190 : 20)
            }

            window.requestAnimationFrame(step)
        })
    }, [clearCursorBadgeTimeout, clearCursorLoadingSafetyTimeout, scheduleCursorBadgeHide])

    const ensureDirectoryLoaded = useCallback(async (directoryPath?: string) => {
        if (!desktopPathRef.current) {
            const initialDirectoryData = await loadDirectory(directoryPath)
            await waitForUi()
            return initialDirectoryData
        }

        if (!directoryPath || normalizePath(currentPathRef.current || '') === normalizePath(directoryPath)) {
            return {
                desktopPath: desktopPathRef.current,
                currentPath: currentPathRef.current,
                parentPath: parentPathRef.current,
                breadcrumbs: breadcrumbsRef.current,
                entries: entriesRef.current
            }
        }

        const directoryData = await loadDirectory(directoryPath)
        await waitForUi()
        return directoryData
    }, [loadDirectory])

    const moveToEntryInDesktop = useCallback(async (entryPath: string, payload: AgentCursorMovePayload) => {
        const desktopRoot = desktopPathRef.current || (await ensureDirectoryLoaded()).desktopPath
        const resolvedEntryPath = coercePathToDesktopRoot(entryPath)
        logDesktopDebug('move_to_entry_start', {
            entryPath,
            resolvedEntryPath,
            action: payload.action ?? null,
            target: payload.target
        })
        if (!desktopRoot || !normalizePath(resolvedEntryPath).startsWith(normalizePath(desktopRoot))) {
            logDesktopDebug('move_to_entry_rejected_outside_root', {
                entryPath,
                resolvedEntryPath,
                desktopRoot
            })
            return false
        }

        const parentDirectory = getParentDirectoryPath(resolvedEntryPath)
        if (normalizePath(currentPathRef.current || '') !== normalizePath(parentDirectory)) {
            logDesktopDebug('move_to_entry_rejected_wrong_folder', {
                entryPath,
                resolvedEntryPath,
                parentDirectory
            })
            return false
        }

        setActiveEntryPath(resolvedEntryPath)
        activeEntryPathRef.current = resolvedEntryPath
        const targetButton = await waitForEntryButton(resolvedEntryPath)
        await animateCursorToPoint(
            getNodePoint(targetButton) ?? getEntryPoint(resolvedEntryPath) ?? getCursorTargetPoint('folder-grid'),
            payload
        )
        logDesktopDebug('move_to_entry_success', {
            entryPath,
            resolvedEntryPath,
            parentDirectory
        })
        return true
    }, [
        animateCursorToPoint,
        ensureDirectoryLoaded,
        getCursorTargetPoint,
        getEntryPoint,
        getNodePoint,
        logDesktopDebug,
        waitForEntryButton
    ])

    const openFolderFromUiControl = useCallback(async (
        folderPath: string,
        payload: AgentCursorMovePayload,
        button: HTMLButtonElement | null
    ) => {
        logDesktopDebug('open_folder_from_ui_control_start', {
            folderPath,
            hasButton: !!button,
            action: payload.action ?? null
        })
        await animateCursorToPoint(
            getNodePoint(button) ?? getCursorTargetPoint('header-controls'),
            {
                ...payload,
                target: 'header-controls',
                click: true,
                label: payload.label ?? getPathLeafName(folderPath)
            }
        )

        await loadDirectory(folderPath)
        const didOpenFolder = await waitForDirectoryPath(folderPath)
        logDesktopDebug('open_folder_from_ui_control_result', {
            folderPath,
            didOpenFolder
        })
        return didOpenFolder
    }, [animateCursorToPoint, getCursorTargetPoint, getNodePoint, loadDirectory, logDesktopDebug, waitForDirectoryPath])

    const openDirectoryEntryInDesktop = useCallback(async (
        folderPath: string,
        payload: AgentCursorMovePayload
    ) => {
        const parentDirectory = getParentDirectoryPath(folderPath)
        logDesktopDebug('open_directory_entry_start', {
            folderPath,
            parentDirectory
        })
        if (normalizePath(currentPathRef.current || '') !== normalizePath(parentDirectory)) {
            logDesktopDebug('open_directory_entry_rejected_wrong_folder', {
                folderPath,
                parentDirectory
            })
            return false
        }

        const targetEntry = entriesRef.current.find(
            (entry) => normalizePath(entry.path) === normalizePath(folderPath) && entry.kind === 'directory'
        )
        if (!targetEntry) {
            logDesktopDebug('open_directory_entry_missing_target', {
                folderPath,
                parentDirectory
            })
            return false
        }

        const didMoveToFolder = await moveToEntryInDesktop(folderPath, {
            ...payload,
            target: 'folder-grid',
            click: true,
            label: payload.label ?? `Open ${getPathLeafName(folderPath)}`
        })
        if (!didMoveToFolder) {
            logDesktopDebug('open_directory_entry_move_failed', {
                folderPath
            })
            return false
        }

        await activateEntry(targetEntry)
        const didOpenFolder = await waitForDirectoryPath(folderPath)
        logDesktopDebug('open_directory_entry_result', {
            folderPath,
            didOpenFolder
        })
        return didOpenFolder
    }, [
        activateEntry,
        getParentDirectoryPath,
        logDesktopDebug,
        moveToEntryInDesktop,
        normalizePath,
        waitForDirectoryPath
    ])

    const navigateToFolderInDesktop = useCallback(async (
        folderPath: string,
        payload: AgentCursorMovePayload
    ) => {
        const desktopRoot = desktopPathRef.current || (await ensureDirectoryLoaded()).desktopPath
        const resolvedFolderPath = coercePathToDesktopRoot(folderPath)
        logDesktopDebug('navigate_to_folder_start', {
            folderPath,
            resolvedFolderPath,
            desktopRoot,
            action: payload.action ?? null
        })
        if (!desktopRoot || !normalizePath(resolvedFolderPath).startsWith(normalizePath(desktopRoot))) {
            logDesktopDebug('navigate_to_folder_rejected_outside_root', {
                folderPath,
                resolvedFolderPath,
                desktopRoot
            })
            return false
        }

        if (!currentPathRef.current) {
            await ensureDirectoryLoaded(desktopRoot)
        }

        const normalizedFolderPath = normalizePath(resolvedFolderPath)
        if (normalizePath(currentPathRef.current || '') === normalizedFolderPath) {
            logDesktopDebug('navigate_to_folder_already_current', {
                folderPath,
                resolvedFolderPath
            })
            return true
        }

        const currentSegments = relativeSegments(desktopRoot, currentPathRef.current || desktopRoot)
        const targetSegments = relativeSegments(desktopRoot, resolvedFolderPath)
        const sharedPrefixLength = getSharedPrefixLength(currentSegments, targetSegments)

        for (let index = currentSegments.length - 1; index >= sharedPrefixLength; index -= 1) {
            const ancestorSegments = currentSegments.slice(0, index)
            const ancestorPath = buildPathFromSegments(desktopRoot, ancestorSegments)
            const ancestorLabel =
                ancestorSegments[ancestorSegments.length - 1]
                ?? getPathLeafName(desktopRoot)
            const didOpenAncestor = await openFolderFromUiControl(
                ancestorPath,
                {
                    ...payload,
                    target: 'header-controls',
                    click: true,
                    label: ancestorLabel
                },
                ancestorPath === desktopRoot
                    ? (desktopRootButtonRef.current ?? breadcrumbRefs.current.get(ancestorPath) ?? null)
                    : (
                        parentPathRef.current
                        && normalizePath(parentPathRef.current) === normalizePath(ancestorPath)
                    )
                        ? upOneLevelButtonRef.current
                        : (breadcrumbRefs.current.get(ancestorPath) ?? null)
            )
            if (!didOpenAncestor) {
                logDesktopDebug('navigate_to_folder_ancestor_failed', {
                    folderPath,
                    resolvedFolderPath,
                    ancestorPath
                })
                return false
            }
        }

        for (let index = sharedPrefixLength; index < targetSegments.length; index += 1) {
            const nextPath = buildPathFromSegments(desktopRoot, targetSegments.slice(0, index + 1))
            const didOpenChildDirectory = await openDirectoryEntryInDesktop(
                nextPath,
                {
                    ...payload,
                    target: 'folder-grid',
                    click: true,
                    label: payload.label ?? `Open ${targetSegments[index]}`
                }
            )
            if (!didOpenChildDirectory) {
                logDesktopDebug('navigate_to_folder_child_failed', {
                    folderPath,
                    resolvedFolderPath,
                    nextPath
                })
                return false
            }
        }

        const didReachTargetFolder =
            normalizePath(currentPathRef.current || '') === normalizedFolderPath
        logDesktopDebug('navigate_to_folder_result', {
            folderPath,
            resolvedFolderPath,
            didReachTargetFolder
        })
        return didReachTargetFolder
    }, [
        buildPathFromSegments,
        ensureDirectoryLoaded,
        getPathLeafName,
        getSharedPrefixLength,
        logDesktopDebug,
        normalizePath,
        openDirectoryEntryInDesktop,
        openFolderFromUiControl,
        relativeSegments
    ])

    const showFolderInDesktop = useCallback(async (folderPath: string, payload: AgentCursorMovePayload) => {
        const resolvedFolderPath = coercePathToDesktopRoot(folderPath)
        logDesktopDebug('show_folder_start', {
            folderPath,
            resolvedFolderPath,
            action: payload.action ?? null
        })
        const didShowFolder = await navigateToFolderInDesktop(resolvedFolderPath, payload)
        if (!didShowFolder) {
            logDesktopDebug('show_folder_failed', {
                folderPath,
                resolvedFolderPath
            })
            return false
        }

        setActiveEntryPath(null)
        activeEntryPathRef.current = null
        await waitForUi(100)
        await animateCursorToPoint(
            getCursorTargetPoint('current-folder-card'),
            {
                ...payload,
                target: 'current-folder-card',
                label: payload.label ?? getPathLeafName(resolvedFolderPath)
            }
        )
        logDesktopDebug('show_folder_success', {
            folderPath,
            resolvedFolderPath
        })
        return true
    }, [
        animateCursorToPoint,
        getCursorTargetPoint,
        getPathLeafName,
        logDesktopDebug,
        navigateToFolderInDesktop
    ])

    const clickFolderInDesktop = useCallback(async (folderPath: string, payload: AgentCursorMovePayload) => {
        const resolvedFolderPath = coercePathToDesktopRoot(folderPath)
        logDesktopDebug('click_folder_start', {
            folderPath,
            resolvedFolderPath,
            action: payload.action ?? null
        })
        const didOpenFolder = await navigateToFolderInDesktop(resolvedFolderPath, {
            ...payload,
            click: true
        })
        if (!didOpenFolder) {
            logDesktopDebug('click_folder_failed', {
                folderPath,
                resolvedFolderPath
            })
            return false
        }

        setActiveEntryPath(null)
        activeEntryPathRef.current = null
        await waitForUi(180)
        await animateCursorToPoint(
            getCursorTargetPoint('current-folder-card'),
            {
                ...payload,
                target: 'current-folder-card',
                label: `Inside ${getPathLeafName(resolvedFolderPath)}`
            }
        )
        logDesktopDebug('click_folder_success', {
            folderPath,
            resolvedFolderPath
        })
        return true
    }, [
        animateCursorToPoint,
        getCursorTargetPoint,
        getPathLeafName,
        logDesktopDebug,
        navigateToFolderInDesktop
    ])

    const readFileInDesktop = useCallback(async (filePath: string, payload: AgentCursorMovePayload) => {
        const resolvedFilePath = coercePathToDesktopRoot(filePath)
        const parentDirectory = getParentDirectoryPath(resolvedFilePath)
        logDesktopDebug('read_file_start', {
            filePath,
            resolvedFilePath,
            parentDirectory
        })
        if (normalizePath(currentPathRef.current || '') !== normalizePath(parentDirectory)) {
            const didShowParentFolder = await showFolderInDesktop(parentDirectory, {
                ...payload,
                action: 'show_folder',
                target: 'current-folder-card',
                reason: 'Open the selected folder before starting file inspection.',
                label: getPathLeafName(parentDirectory),
                click: true,
                path: parentDirectory
            })
            if (!didShowParentFolder) {
                logDesktopDebug('read_file_parent_folder_failed', {
                    filePath,
                    resolvedFilePath,
                    parentDirectory
                })
                return false
            }
        }

        const isEntryAlreadyFocused =
            !!activeEntryPathRef.current
            && normalizePath(activeEntryPathRef.current) === normalizePath(resolvedFilePath)
            && normalizePath(currentPathRef.current || '') === normalizePath(parentDirectory)

        if (!isEntryAlreadyFocused) {
            const didMoveToFile = await moveToEntryInDesktop(resolvedFilePath, {
                ...payload,
                target: 'folder-grid',
                label: `Inspect ${getPathLeafName(resolvedFilePath)}`,
                click: true
            })
            if (!didMoveToFile) {
                logDesktopDebug('read_file_move_failed', {
                    filePath,
                    resolvedFilePath
                })
                return false
            }
        }

        await animateCursorToPoint(
            getCursorTargetPoint('inspector-panel'),
            {
                ...payload,
                target: 'inspector-panel',
                label: payload.label ?? `Read ${getPathLeafName(resolvedFilePath)}`
            }
        )
        logDesktopDebug('read_file_success', {
            filePath,
            resolvedFilePath
        })
        return true
    }, [
        animateCursorToPoint,
        getCursorTargetPoint,
        logDesktopDebug,
        moveToEntryInDesktop,
        normalizePath,
        showFolderInDesktop
    ])

    const revealPathInDesktop = useCallback(async (payload: AgentCursorMovePayload) => {
        const targetPath = payload.path
        if (!targetPath) {
            return false
        }

        if (!desktopPathRef.current) {
            await loadDirectory()
            await waitForUi()
        }

        const desktopRoot = desktopPathRef.current
        const resolvedTargetPath = coercePathToDesktopRoot(targetPath)
        if (!desktopRoot || !normalizePath(resolvedTargetPath).startsWith(normalizePath(desktopRoot))) {
            return false
        }

        if (normalizePath(currentPathRef.current || '') !== normalizePath(desktopRoot)) {
            await loadDirectory(currentPathRef.current || desktopRoot)
            await waitForUi()
        }

        const targetSegments = relativeSegments(desktopRoot, resolvedTargetPath)
        if (targetSegments.length === 0) {
            const currentSegments = relativeSegments(desktopRoot, currentPathRef.current || desktopRoot)

            for (let index = currentSegments.length - 1; index >= 0; index -= 1) {
                if (!parentPathRef.current) {
                    break
                }

                await animateCursorToPoint(getCursorTargetPoint('header-controls'), {
                    target: 'header-controls',
                    reason: 'Navigate up to the consulting root',
                    label: `Exit ${currentSegments[index]}`,
                    click: true
                })
                await loadDirectory(parentPathRef.current)
                await waitForUi()
            }

            await animateCursorToPoint(getCursorTargetPoint('current-folder-card'), {
                ...payload,
                label: payload.label ?? 'BLUEBARRY'
            })
            return true
        }

        const currentSegments = relativeSegments(
            desktopRoot,
            currentPathRef.current || desktopRoot
        )
        const targetParentSegments = targetSegments.slice(0, -1)
        const sharedPrefixLength = getSharedPrefixLength(
            currentSegments,
            targetParentSegments
        )

        for (let index = currentSegments.length - 1; index >= sharedPrefixLength; index -= 1) {
            if (!parentPathRef.current) {
                break
            }

            await animateCursorToPoint(getCursorTargetPoint('header-controls'), {
                target: 'header-controls',
                reason: 'Navigate out of the current folder',
                label: `Exit ${currentSegments[index]}`,
                click: true
            })
            await loadDirectory(parentPathRef.current)
            await waitForUi()
        }

        let workingDirectory = currentPathRef.current || desktopRoot
        for (let index = sharedPrefixLength; index < targetParentSegments.length; index += 1) {
            const nextSegment = targetParentSegments[index]
            const nextPath = joinWindowsPath(workingDirectory, nextSegment)
            const directoryData = await loadDirectory(workingDirectory)
            await waitForUi()

            const nextEntry = directoryData.entries.find(
                (entry) => normalizePath(entry.path) === normalizePath(nextPath)
            )
            setActiveEntryPath(nextPath)
            await animateCursorToPoint(
                getEntryPoint(nextPath) ?? getCursorTargetPoint('folder-grid'),
                {
                    ...payload,
                    label: `Enter ${nextSegment}`,
                    click: true
                }
            )

            if (nextEntry?.kind === 'directory') {
                const nestedDirectoryData = await loadDirectory(nextEntry.path)
                await waitForUi()
                await animateCursorToPoint(
                    getCursorTargetPoint('current-folder-card'),
                    {
                        target: 'current-folder-card',
                        reason: 'Confirm the folder that was opened for template inspection.',
                        label: `Inside ${nextSegment}`
                    }
                )
                await waitForUi(180)
                workingDirectory = nestedDirectoryData.currentPath
                continue
            }

            workingDirectory = nextPath
        }

        const finalPath = resolvedTargetPath
        const finalDirectory = targetParentSegments.reduce(
            (currentPath, segment) => joinWindowsPath(currentPath, segment),
            desktopRoot
        )
        const finalDirectoryData = await loadDirectory(finalDirectory)
        await waitForUi()

        const finalEntry = finalDirectoryData.entries.find(
            (entry) => normalizePath(entry.path) === normalizePath(finalPath)
        )

        setActiveEntryPath(finalPath)
        await animateCursorToPoint(
            getEntryPoint(finalPath) ?? getCursorTargetPoint('folder-grid'),
            payload
        )

        if (payload.navigate && finalEntry?.kind === 'directory') {
            await loadDirectory(finalEntry.path)
            await waitForUi()
        }

        return true
    }, [animateCursorToPoint, getCursorTargetPoint, getEntryPoint, loadDirectory])

    const animateCursorMove = useCallback(async (payload: AgentCursorMovePayload) => {
        logDesktopDebug('animate_cursor_move_start', {
            payload
        })
        if (payload.action === 'click_folder' && payload.path) {
            const didClickFolder = await clickFolderInDesktop(payload.path, payload)
            if (didClickFolder) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'click_folder'
                })
                return
            }

            const didShowFolder = await showFolderInDesktop(payload.path, {
                ...payload,
                action: 'show_folder',
                target: 'current-folder-card',
                reason: 'Show the folder in the desktop view before inspection continues.',
                label: payload.label ?? getPathLeafName(payload.path),
                click: true
            })
            if (didShowFolder) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'click_folder_show_folder_fallback'
                })
                return
            }
        }

        if (payload.action === 'show_folder' && payload.path) {
            const didShowFolder = await showFolderInDesktop(payload.path, payload)
            if (didShowFolder) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'show_folder'
                })
                return
            }
        }

        if (payload.action === 'move_to_folder' && payload.path) {
            const didMoveToFolder = await moveToEntryInDesktop(payload.path, {
                ...payload,
                target: 'folder-grid'
            })
            if (didMoveToFolder) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'move_to_folder'
                })
                return
            }
        }

        if (payload.action === 'move_to_file' && payload.path) {
            const didMoveToFile = await moveToEntryInDesktop(payload.path, {
                ...payload,
                target: 'folder-grid'
            })
            if (didMoveToFile) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'move_to_file'
                })
                return
            }

            const parentDirectory = getParentDirectoryPath(payload.path)
            const didShowParentFolder = await showFolderInDesktop(parentDirectory, {
                ...payload,
                action: 'show_folder',
                target: 'current-folder-card',
                reason: 'Open the selected folder before moving onto the file.',
                label: getPathLeafName(parentDirectory),
                click: true,
                path: parentDirectory
            })
            if (didShowParentFolder) {
                const retriedMoveToFile = await moveToEntryInDesktop(payload.path, {
                    ...payload,
                    target: 'folder-grid'
                })
                if (retriedMoveToFile) {
                    logDesktopDebug('animate_cursor_move_complete', {
                        payload,
                        branch: 'move_to_file_after_show_folder'
                    })
                    return
                }
            }
        }

        if (payload.action === 'read_file' && payload.path) {
            const didReadFile = await readFileInDesktop(payload.path, payload)
            if (didReadFile) {
                logDesktopDebug('animate_cursor_move_complete', {
                    payload,
                    branch: 'read_file'
                })
                return
            }
        }

        const revealed = await revealPathInDesktop(payload)
        if (revealed) {
            logDesktopDebug('animate_cursor_move_complete', {
                payload,
                branch: 'reveal_path'
            })
            return
        }

        await animateCursorToPoint(getCursorTargetPoint(payload.target), payload)
        logDesktopDebug('animate_cursor_move_complete', {
            payload,
            branch: 'fallback_cursor_target'
        })
    }, [
        animateCursorToPoint,
        clickFolderInDesktop,
        getCursorTargetPoint,
        logDesktopDebug,
        moveToEntryInDesktop,
        readFileInDesktop,
        revealPathInDesktop,
        showFolderInDesktop
    ])

    useEffect(() => {
        animateCursorMoveRef.current = animateCursorMove
    }, [animateCursorMove])

    useEffect(() => {
        const handleFilesystemUpdated = (_event: unknown, payload?: { changedPaths?: string[] }) => {
            logDesktopDebug('desktop_filesystem_updated_event', {
                payload
            })
            setCursorLoading(false)
            scheduleCursorBadgeHide(1400)
            void loadDirectoryRef.current(currentPathRef.current || undefined)
        }

        const handleAgentCursorMove = (_event: unknown, payload: AgentCursorMovePayload) => {
            logDesktopDebug('desktop_agent_cursor_move_received', {
                payload
            })
            activeCursorMovesRef.current += 1
            cursorSequenceRef.current = cursorSequenceRef.current
                .then(() => animateCursorMoveRef.current(payload))
                .catch((error) => {
                    logDesktopDebug('desktop_agent_cursor_move_error', {
                        payload,
                        error: error instanceof Error
                            ? { message: error.message, stack: error.stack }
                            : String(error)
                    })
                    console.error('Failed to animate desktop cursor move:', error)
                })
                .finally(() => {
                    if (payload.eventId) {
                        logDesktopDebug('desktop_agent_cursor_move_ack', {
                            eventId: payload.eventId
                        })
                        window.desktopAPI.acknowledgeCursorMove(payload.eventId)
                    }
                    activeCursorMovesRef.current = Math.max(0, activeCursorMovesRef.current - 1)
                    if (activeCursorMovesRef.current === 0 && pendingCursorClearRef.current) {
                        applyPendingCursorClear()
                    }
                })
        }

        const handleFileConfirmationRequest = (_event: unknown, payload: FileConfirmationRequest) => {
            setPendingConfirmation(payload)
        }

        const handleDesktopActionFeedback = (_event: unknown, payload?: DesktopActionFeedbackPayload) => {
            logDesktopDebug('desktop_action_feedback_received', {
                payload
            })
            applyDesktopActionFeedback(payload)
        }

        window.electron.ipcRenderer.on('desktop-filesystem-updated', handleFilesystemUpdated)
        window.electron.ipcRenderer.on('desktop-action-feedback', handleDesktopActionFeedback)
        window.electron.ipcRenderer.on('desktop-agent-cursor-move', handleAgentCursorMove)
        window.electron.ipcRenderer.on(
            'desktop-agent-file-confirmation-request',
            handleFileConfirmationRequest
        )
        logDesktopDebug('desktop_renderer_ready')
        window.desktopAPI.signalReady()

        return () => {
            clearCursorBadgeTimeout()
            clearCursorLoadingSafetyTimeout()
            for (const timeoutId of actionToastTimeoutsRef.current.values()) {
                window.clearTimeout(timeoutId)
            }
            actionToastTimeoutsRef.current.clear()
            window.electron.ipcRenderer.removeListener(
                'desktop-filesystem-updated',
                handleFilesystemUpdated
            )
            window.electron.ipcRenderer.removeListener(
                'desktop-action-feedback',
                handleDesktopActionFeedback
            )
            window.electron.ipcRenderer.removeListener(
                'desktop-agent-cursor-move',
                handleAgentCursorMove
            )
            window.electron.ipcRenderer.removeListener(
                'desktop-agent-file-confirmation-request',
                handleFileConfirmationRequest
            )
        }
    }, [applyDesktopActionFeedback, applyPendingCursorClear, clearCursorBadgeTimeout, clearCursorLoadingSafetyTimeout, logDesktopDebug, scheduleCursorBadgeHide])

    useEffect(() => {
        const interval = setInterval(() => setNow(new Date()), 1000)
        return () => clearInterval(interval)
    }, [])

    useEffect(() => {
        const loadMessages = async () => {
            try {
                const storedMessages = await window.desktopAPI.getMessages()
                setChatMessages(normalizeDesktopChatMessages(storedMessages))
            } catch (error) {
                console.error('Failed to load desktop chat messages:', error)
            }
        }

        const handleMessagesUpdated = (updatedMessages: any[]) => {
            setChatMessages(normalizeDesktopChatMessages(updatedMessages))
        }

        void loadMessages()
        window.desktopAPI.onMessagesUpdated(handleMessagesUpdated)

        return () => {
            window.desktopAPI.removeMessagesUpdatedListener()
        }
    }, [])

    useEffect(() => {
        const container = conversationScrollRef.current
        if (!container) {
            return
        }

        container.scrollTop = container.scrollHeight
    }, [chatMessages])

    const handleChatSubmit = useCallback(async (event?: React.FormEvent<HTMLFormElement>) => {
        event?.preventDefault()

        const message = chatDraft.trim()
        if (!message || isSendingChat) {
            return
        }

        setIsSendingChat(true)
        setChatDraft('')

        try {
            await window.desktopAPI.sendChatMessage({
                message,
                messageId: `desktop-chat-${Date.now()}`
            })
        } catch (error) {
            console.error('Failed to send desktop chat message:', error)
            setChatDraft(message)
        } finally {
            setIsSendingChat(false)
        }
    }, [chatDraft, isSendingChat])

    const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
        setCursorVisible(true)
        updateCursorPosition(event.clientX, event.clientY)
    }

    const handleMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
        setCursorPressed(true)
        createCursorWave(event.clientX, event.clientY)
    }

    const formattedTime = now.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit'
    })

    const formattedDate = now.toLocaleDateString([], {
        weekday: 'long',
        month: 'short',
        day: 'numeric'
    })

    return (
        <div
            ref={rootRef}
            className="relative h-screen overflow-hidden cursor-none text-slate-50"
            onMouseMove={handleMouseMove}
            onMouseEnter={() => setCursorVisible(true)}
            onMouseLeave={() => {
                setCursorVisible(false)
                setCursorPressed(false)
            }}
            onMouseDown={handleMouseDown}
            onMouseUp={() => setCursorPressed(false)}
        >
            <div className="desktop-wallpaper absolute inset-0" />
            <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,32,0.18),rgba(8,17,32,0.42))]" />

            {pendingConfirmation && (
                <div className="app-region-no-drag absolute left-0 right-0 top-24 z-[95] flex justify-center px-4">
                    <div
                        className="flex w-full max-w-3xl select-none flex-wrap items-center justify-between gap-4 rounded-[28px] border border-amber-200/25 bg-[rgba(10,18,30,0.82)] px-5 py-4 shadow-[0_28px_70px_rgba(8,17,32,0.45)] backdrop-blur-2xl"
                        onClick={(event) => event.stopPropagation()}
                        onMouseDown={(event) => event.stopPropagation()}
                    >
                        <div className="min-w-0 flex-1">
                            <p className="text-[11px] uppercase tracking-[0.22em] text-amber-100/70">
                                Desktop confirmation
                            </p>
                            <p className="mt-1 text-sm font-semibold text-slate-50">
                                {pendingConfirmation.message}
                            </p>
                            <p className="mt-2 break-words whitespace-pre-wrap text-sm leading-6 text-slate-200/78">
                                {pendingConfirmation.path}
                            </p>
                        </div>

                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                onClick={() => {
                                    window.desktopAPI.respondToAgentFileConfirmation(
                                        pendingConfirmation.requestId,
                                        false
                                    )
                                    setPendingConfirmation(null)
                                }}
                                className="app-region-no-drag rounded-full border border-white/15 bg-white/[0.06] px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-white/[0.12]"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    window.desktopAPI.respondToAgentFileConfirmation(
                                        pendingConfirmation.requestId,
                                        true
                                    )
                                    setPendingConfirmation(null)
                                }}
                                className="app-region-no-drag rounded-full border border-emerald-300/20 bg-emerald-400/18 px-4 py-2 text-sm font-semibold text-emerald-50 transition-colors hover:bg-emerald-400/26"
                            >
                                Create File
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {actionToasts.length > 0 && (
                <div className="pointer-events-none absolute right-4 top-24 z-[94] flex w-[min(420px,calc(100%-2rem))] flex-col gap-3 sm:right-7">
                    {actionToasts.map((toast) => {
                        const { Icon, iconClassName, iconSurfaceClassName } = getToastVisual(toast.kind)
                        return (
                            <div
                                key={toast.id}
                                className="pointer-events-auto relative overflow-hidden rounded-[28px] border border-white/14 bg-[rgba(8,17,32,0.88)] shadow-[0_28px_70px_rgba(8,17,32,0.45)] backdrop-blur-2xl"
                            >
                                <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(125,211,252,0.18),transparent_48%),linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.02))]" />
                                <div className="relative flex items-start gap-4 px-5 py-4">
                                    <div className={cn(
                                        'mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-2xl border border-white/10',
                                        iconSurfaceClassName
                                    )}>
                                        <Icon className={cn('size-5', iconClassName)} />
                                    </div>

                                    <div className="min-w-0 flex-1">
                                        <p className="text-[11px] uppercase tracking-[0.22em] text-slate-200/58">
                                            Desktop update
                                        </p>
                                        <p className="mt-1 text-sm font-semibold text-slate-50">
                                            {toast.title}
                                        </p>
                                        {toast.description && (
                                            <p className="mt-2 text-sm leading-6 text-slate-200/78">
                                                {toast.description}
                                            </p>
                                        )}
                                    </div>

                                    <button
                                        type="button"
                                        onClick={() => dismissActionToast(toast.id)}
                                        className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-200/70 transition-colors hover:bg-white/[0.1] hover:text-slate-50"
                                    >
                                        Close
                                    </button>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}

            <div className="relative flex h-full min-h-0 flex-col">
                <header className="app-region-drag shrink-0 px-4 pb-4 pt-5 sm:px-7">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div className="flex min-w-0 items-center gap-4">
                        <div className="flex size-12 items-center justify-center rounded-[18px] border border-white/15 bg-white/10 shadow-[0_18px_40px_rgba(8,17,32,0.28)] backdrop-blur-xl">
                            <Monitor className="size-6 text-sky-100" />
                        </div>
                        <div className="min-w-0">
                            <div className="flex items-center gap-2">
                                <h1 className="text-xl font-semibold tracking-tight text-slate-50">Desktop Mirror</h1>
                                <span className="rounded-full border border-emerald-300/25 bg-emerald-400/15 px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.2em] text-emerald-100">
                                    Live
                                </span>
                            </div>
                            <p className="mt-1 text-sm text-slate-200/72">
                                Browse Desktop folders inside Blueberry and open real files directly.
                            </p>
                        </div>
                        </div>

                        <div className="app-region-no-drag flex flex-wrap items-center gap-3">
                        <button
                            ref={desktopRootButtonRef}
                            type="button"
                            onClick={() => void loadDirectory(desktopPath || undefined)}
                            className="flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.08] px-4 py-2 text-sm font-medium text-slate-50 backdrop-blur-md transition-colors hover:bg-white/[0.14]"
                        >
                            <House className="size-4" />
                            Desktop Root
                        </button>
                        <button
                            ref={upOneLevelButtonRef}
                            type="button"
                            onClick={() => parentPath && void loadDirectory(parentPath)}
                            disabled={!parentPath}
                            className={cn(
                                'flex items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-sm font-medium backdrop-blur-md transition-colors',
                                parentPath
                                    ? 'bg-white/[0.08] text-slate-50 hover:bg-white/[0.14]'
                                    : 'cursor-not-allowed bg-white/[0.04] text-slate-200/38'
                            )}
                        >
                            <ArrowLeft className="size-4" />
                            Up One Level
                        </button>
                        <button
                            type="button"
                            onClick={() => void loadDirectory(currentPath || undefined)}
                            className="flex items-center gap-2 rounded-full border border-sky-300/25 bg-sky-300/12 px-4 py-2 text-sm font-medium text-sky-50 backdrop-blur-md transition-colors hover:bg-sky-300/20"
                        >
                            <RefreshCcw className={cn('size-4', isLoading && 'animate-spin')} />
                            Refresh
                        </button>
                        </div>
                    </div>
                </header>

                <main className="relative grid min-h-0 flex-1 gap-4 px-4 pb-4 sm:px-7 lg:grid-cols-[minmax(0,1fr)_minmax(280px,320px)]">
                    <section
                        className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-[34px] border border-white/12 bg-white/[0.06] px-4 pb-4 pt-5 shadow-[0_28px_80px_rgba(8,17,32,0.34)] backdrop-blur-xl sm:px-6 sm:pb-6"
                        onClick={(event) => {
                            if (event.target === event.currentTarget) {
                                setActiveEntryPath(null)
                            }
                        }}
                    >
                        <div className="mb-5 flex shrink-0 flex-wrap items-center justify-between gap-3">
                            <div className="flex items-center gap-3">
                                <div className="flex size-10 items-center justify-center rounded-2xl bg-white/10">
                                    <HardDrive className="size-5 text-slate-100" />
                                </div>
                                <div>
                                    <p className="text-xs uppercase tracking-[0.24em] text-slate-200/60">
                                        Current Folder
                                    </p>
                                    <p className="text-sm text-slate-100/90">
                                        {folderCount} folders and {fileCount} files
                                    </p>
                                </div>
                            </div>

                            <div className="rounded-full border border-white/10 bg-black/10 px-3 py-1 text-xs text-slate-200/72">
                                Click folders to enter them. Click files to open them.
                            </div>
                        </div>

                        <div className="mb-5 shrink-0 overflow-x-auto pb-1">
                            <div className="flex min-w-max items-center gap-2">
                            {breadcrumbs.map((breadcrumb, index) => (
                                <React.Fragment key={breadcrumb.path}>
                                    {index > 0 && (
                                        <ChevronRight className="size-3.5 text-slate-300/55" />
                                    )}
                                    <button
                                        ref={(node) => registerBreadcrumbRef(breadcrumb.path, node)}
                                        type="button"
                                        onClick={() => void loadDirectory(breadcrumb.path)}
                                        className={cn(
                                            'rounded-full border px-3 py-1.5 text-xs font-medium backdrop-blur-md transition-colors',
                                            index === breadcrumbs.length - 1
                                                ? 'border-sky-300/20 bg-sky-300/14 text-sky-50'
                                                : 'border-white/10 bg-black/10 text-slate-200/80 hover:bg-white/10'
                                        )}
                                    >
                                        {breadcrumb.name}
                                    </button>
                                </React.Fragment>
                            ))}
                            </div>
                        </div>

                        {error && (
                            <div className="mb-4 shrink-0 rounded-2xl border border-rose-300/20 bg-rose-300/12 px-4 py-3 text-sm text-rose-50">
                                {error}
                            </div>
                        )}

                        <div className="min-h-0 flex-1 overflow-auto pr-2">
                            {entries.length === 0 && !isLoading ? (
                            <div className="flex min-h-full items-center justify-center">
                                <div className="max-w-sm rounded-[30px] border border-dashed border-white/18 bg-black/10 px-8 py-10 text-center backdrop-blur-md">
                                    <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-3xl bg-white/[0.08]">
                                        <FolderOpen className="size-8 text-sky-100" />
                                    </div>
                                    <h2 className="text-lg font-semibold text-slate-50">This folder is empty</h2>
                                    <p className="mt-2 text-sm leading-6 text-slate-200/72">
                                        Subfolders and files from your real Desktop hierarchy will appear here when present.
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <div ref={iconFieldRef} className="desktop-icon-field min-h-full w-max pb-2 pr-8">
                                {entries.map((entry) => (
                                    <DesktopIcon
                                        key={entry.path}
                                        entry={entry}
                                        isActive={activeEntry?.path === entry.path}
                                        onActivate={(currentEntry) => void activateEntry(currentEntry)}
                                        onPreview={(currentEntry) => setActiveEntryPath(currentEntry.path)}
                                        buttonRef={(node) => registerEntryRef(entry.path, node)}
                                    />
                                ))}
                            </div>
                        )}
                        </div>
                    </section>

                    <aside className="min-h-0 overflow-auto lg:pr-1">
                        <div className="flex min-h-0 flex-col gap-4 lg:gap-5">
                        <div className="rounded-[30px] border border-white/12 bg-white/[0.08] p-5 shadow-[0_24px_60px_rgba(8,17,32,0.28)] backdrop-blur-xl">
                            <div className="mb-4 flex items-center gap-3">
                                <div className="flex size-10 items-center justify-center rounded-2xl bg-sky-300/14">
                                    <Sparkles className="size-5 text-sky-100" />
                                </div>
                                <div>
                                    <p className="text-xs uppercase tracking-[0.22em] text-slate-200/58">Focused Item</p>
                                    <p className="text-sm text-slate-100/85">What the cursor is currently on</p>
                                </div>
                            </div>

                            {activeEntry ? (
                                <>
                                    <div className="rounded-[24px] border border-white/10 bg-black/10 p-4">
                                        <div className="mb-3 flex items-center gap-3">
                                            <div className="flex size-12 items-center justify-center rounded-2xl bg-white/10">
                                                {activeEntry.kind === 'directory' ? (
                                                    <Folder className="size-6 text-sky-100" />
                                                ) : (
                                                    React.createElement(getEntryVisual(activeEntry).Icon, {
                                                        className: cn('size-6', getEntryVisual(activeEntry).accent)
                                                    })
                                                )}
                                            </div>
                                            <div className="min-w-0">
                                                <h2 className="truncate text-base font-semibold text-slate-50">
                                                    {activeEntry.name}
                                                </h2>
                                                <p className="truncate text-xs uppercase tracking-[0.16em] text-slate-200/62">
                                                    {activeEntry.kind === 'directory'
                                                        ? 'Folder'
                                                        : `${activeEntry.extension || 'file'} file`}
                                                </p>
                                            </div>
                                        </div>
                                        <p className="break-words text-xs leading-6 text-slate-200/72">
                                            {activeEntry.path}
                                        </p>
                                    </div>

                                    <button
                                        type="button"
                                        onClick={() =>
                                            activeEntry.kind === 'directory'
                                                ? void loadDirectory(activeEntry.path)
                                                : void openFile(activeEntry)
                                        }
                                        className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-950 transition-transform hover:scale-[0.99]"
                                    >
                                        {activeEntry.kind === 'directory' ? 'Enter Folder' : 'Open File'}
                                    </button>
                                </>
                            ) : (
                                <p className="text-sm leading-6 text-slate-200/72">
                                    Hover an item to inspect it. Folders stay inside this desktop view; files open with their real desktop app.
                                </p>
                            )}
                        </div>

                        <div className="rounded-[30px] border border-white/12 bg-white/[0.08] p-5 shadow-[0_24px_60px_rgba(8,17,32,0.28)] backdrop-blur-xl">
                            <p className="text-xs uppercase tracking-[0.22em] text-slate-200/58">Location</p>
                            <div className="mt-4 grid gap-3">
                                <div className="rounded-2xl border border-white/10 bg-black/10 px-4 py-3">
                                    <p className="text-[11px] uppercase tracking-[0.16em] text-slate-300/50">Desktop root</p>
                                    <p className="mt-2 break-words text-sm leading-6 text-slate-100/82">
                                        {desktopPath || 'Loading...'}
                                    </p>
                                </div>
                                <div className="rounded-2xl border border-white/10 bg-black/10 px-4 py-3">
                                    <p className="text-[11px] uppercase tracking-[0.16em] text-slate-300/50">Current path</p>
                                    <p className="mt-2 break-words text-sm leading-6 text-slate-100/82">
                                        {currentPath || 'Loading...'}
                                    </p>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="rounded-2xl border border-white/10 bg-black/10 px-4 py-3">
                                        <p className="text-[11px] uppercase tracking-[0.16em] text-slate-300/50">Folders</p>
                                        <p className="mt-2 text-2xl font-semibold text-slate-50">{folderCount}</p>
                                    </div>
                                    <div className="rounded-2xl border border-white/10 bg-black/10 px-4 py-3">
                                        <p className="text-[11px] uppercase tracking-[0.16em] text-slate-300/50">Files</p>
                                        <p className="mt-2 text-2xl font-semibold text-slate-50">{fileCount}</p>
                                    </div>
                                </div>
                                <p className="text-sm leading-6 text-slate-200/72">
                                    Folder navigation stays inside Blueberry. Only files hand off to the real operating system when opened.
                                </p>
                            </div>
                        </div>

                        <div className="rounded-[30px] border border-white/12 bg-white/[0.08] p-5 shadow-[0_24px_60px_rgba(8,17,32,0.28)] backdrop-blur-xl">
                            <div className="flex items-center gap-3">
                                <div className="flex size-10 items-center justify-center rounded-2xl bg-sky-300/14">
                                    <MessageSquare className="size-5 text-sky-100" />
                                </div>
                                <div>
                                    <p className="text-xs uppercase tracking-[0.22em] text-slate-200/58">
                                        Conversation
                                    </p>
                                    <p className="text-sm text-slate-100/85">
                                        Clarification questions and replies stay visible here.
                                    </p>
                                </div>
                            </div>

                            <div
                                ref={conversationScrollRef}
                                className="mt-4 max-h-[340px] overflow-auto pr-1"
                            >
                                {chatMessages.length === 0 ? (
                                    <div className="rounded-[24px] border border-dashed border-white/12 bg-black/10 px-4 py-5 text-sm leading-6 text-slate-200/68">
                                        The desktop view will mirror the ongoing chat once the conversation starts.
                                    </div>
                                ) : (
                                    <div className="flex flex-col gap-3">
                                        {chatMessages.map((message) => (
                                            <div
                                                key={message.id}
                                                className={cn(
                                                    'flex',
                                                    message.role === 'user'
                                                        ? 'justify-end'
                                                        : 'justify-start'
                                                )}
                                            >
                                                <div
                                                    className={cn(
                                                        'max-w-[92%] rounded-[24px] px-4 py-3 text-sm leading-6 shadow-[0_18px_35px_rgba(8,17,32,0.2)]',
                                                        message.role === 'user'
                                                            ? 'border border-sky-300/35 bg-sky-700/78 text-slate-50'
                                                            : 'border border-white/14 bg-slate-950/52 text-slate-100'
                                                    )}
                                                >
                                                    <p
                                                        className={cn(
                                                            'mb-2 text-[10px] uppercase tracking-[0.18em]',
                                                            message.role === 'user'
                                                                ? 'text-sky-100/80'
                                                                : 'text-slate-300/72'
                                                        )}
                                                    >
                                                        {message.role === 'user' ? 'You' : 'Blueberry'}
                                                    </p>
                                                    <p className="break-words whitespace-pre-wrap">
                                                        {message.content}
                                                    </p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <form className="mt-4" onSubmit={handleChatSubmit}>
                                <label className="sr-only" htmlFor="desktop-chat-input">
                                    Reply to Blueberry
                                </label>
                                <textarea
                                    id="desktop-chat-input"
                                    value={chatDraft}
                                    onChange={(event) => setChatDraft(event.target.value)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' && !event.shiftKey) {
                                            event.preventDefault()
                                            void handleChatSubmit()
                                        }
                                    }}
                                    placeholder="Reply here when Blueberry asks for clarification..."
                                    rows={4}
                                    className="min-h-[112px] w-full resize-y rounded-[24px] border border-white/14 bg-slate-950/60 px-4 py-3 text-sm leading-6 text-slate-100 outline-none transition-colors placeholder:text-slate-400/80 focus:border-sky-300/32 focus:bg-slate-950/72"
                                />

                                <div className="mt-3 flex items-center justify-between gap-3">
                                    <p className="text-xs leading-5 text-slate-200/58">
                                        Press Enter to send. Use Shift+Enter for a new line.
                                    </p>
                                    <button
                                        type="submit"
                                        disabled={!chatDraft.trim() || isSendingChat}
                                        className={cn(
                                            'flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition-colors',
                                            !chatDraft.trim() || isSendingChat
                                                ? 'cursor-not-allowed border border-white/10 bg-white/[0.05] text-slate-300/40'
                                                : 'border border-sky-300/20 bg-sky-300/14 text-sky-50 hover:bg-sky-300/22'
                                        )}
                                    >
                                        <Send className="size-4" />
                                        {isSendingChat ? 'Sending...' : 'Send'}
                                    </button>
                                </div>
                            </form>
                        </div>
                        </div>
                    </aside>
                </main>

                <footer className="pointer-events-none shrink-0 px-4 pb-4 pt-2 sm:px-7 sm:pb-5">
                    <div className="mx-auto flex max-w-[min(1080px,100%)] flex-wrap items-center justify-between gap-3 rounded-[28px] border border-white/12 bg-black/[0.18] px-4 py-3 shadow-[0_24px_60px_rgba(8,17,32,0.42)] backdrop-blur-2xl sm:px-5">
                        <div className="pointer-events-auto flex items-center gap-3">
                            <div className="flex size-11 items-center justify-center rounded-2xl bg-sky-300/18">
                                <Monitor className="size-5 text-sky-100" />
                            </div>
                            <div>
                                <p className="text-sm font-semibold text-slate-50">PC Desktop View</p>
                                <p className="text-xs text-slate-200/66">Nested folders stay inside this window</p>
                            </div>
                        </div>

                        <div className="pointer-events-auto flex items-center gap-3">
                            <div className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-2 text-xs text-slate-200/72">
                                {formattedDate}
                            </div>
                            <div className="rounded-full border border-white/10 bg-white/[0.06] px-4 py-2 text-sm font-semibold text-slate-50">
                                {formattedTime}
                            </div>
                        </div>
                    </div>
                </footer>
            </div>

            {cursorWaves.map((wave) => (
                <span
                    key={wave.id}
                    className="desktop-click-wave"
                    style={{ left: `${wave.x}px`, top: `${wave.y}px` }}
                />
            ))}

            {cursorVisible && (
                <div
                    ref={cursorRef}
                    className="desktop-cursor pointer-events-none fixed left-0 top-0 z-[80]"
                >
                    <div className="relative -translate-x-[3px] -translate-y-[4px]">
                        <div
                            className={cn(
                                'absolute -left-1 -top-1 size-8 rounded-full bg-sky-300/18 blur-md',
                                cursorPressed && 'scale-125 bg-sky-300/28'
                            )}
                        />
                        {cursorLabel && (
                            <div className="absolute left-6 top-4 max-w-[320px] rounded-2xl border border-white/15 bg-[rgba(8,17,32,0.9)] px-3 py-2 text-sky-50 shadow-[0_12px_30px_rgba(8,17,32,0.34)] backdrop-blur-md">
                                <div className="flex items-center gap-2">
                                    {cursorLoading && (
                                        <span className="size-2 rounded-full bg-sky-300 animate-pulse" />
                                    )}
                                    <span className="text-[11px] font-medium tracking-[0.08em] text-sky-50">
                                        {cursorLabel}
                                    </span>
                                </div>
                                {cursorDescription && (
                                    <p className="mt-1 max-w-[280px] whitespace-normal text-[10px] leading-4 text-slate-200/90">
                                        {cursorDescription}
                                    </p>
                                )}
                            </div>
                        )}
                        <MousePointer2
                            className={cn(
                                'relative size-6 text-white drop-shadow-[0_6px_12px_rgba(8,17,32,0.5)]',
                                cursorPressed && 'scale-90'
                            )}
                            strokeWidth={2.4}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
