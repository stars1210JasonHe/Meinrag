import ChatHistoryPanel from './ChatHistoryPanel'
import FolderTreePanel from './FolderTreePanel'

export default function Sidebar({
  sessions, onNewChat, onSelectSession, onDeleteSession, currentSessionId,
  documents, collections, selectedFilter, onSelectFilter,
  onUpload, onAutoUpload, onDeleteDoc, onDownloadDoc,
  onEditCollections, onReclassify, uploading,
}) {
  return (
    <div className="sidebar">
      <ChatHistoryPanel
        sessions={sessions}
        currentSessionId={currentSessionId}
        onNewChat={onNewChat}
        onSelectSession={onSelectSession}
        onDeleteSession={onDeleteSession}
      />
      <div className="sidebar-divider" />
      <FolderTreePanel
        documents={documents}
        collections={collections}
        selectedFilter={selectedFilter}
        onSelectFilter={onSelectFilter}
        onUpload={onUpload}
        onAutoUpload={onAutoUpload}
        onDeleteDoc={onDeleteDoc}
        onDownloadDoc={onDownloadDoc}
        onEditCollections={onEditCollections}
        onReclassify={onReclassify}
        uploading={uploading}
      />
    </div>
  )
}
