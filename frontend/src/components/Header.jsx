import { User, ChevronDown } from 'lucide-react'
import UserMenu from './UserMenu'

export default function Header({
  documentCount,
  currentUser,
  currentUserObj,
  users,
  showUserMenu,
  setShowUserMenu,
  onSwitchUser,
  onCreateUser,
  userMenuRef,
}) {
  return (
    <div className="header">
      <h1>MEINRAG</h1>
      <div className="header-info">
        <span>{documentCount} {documentCount === 1 ? 'document' : 'documents'}</span>
        <div className="user-selector" ref={userMenuRef}>
          <button className="user-btn" onClick={() => setShowUserMenu(!showUserMenu)}>
            <User size={16} />
            <span>{currentUserObj?.display_name || currentUser}</span>
            <ChevronDown size={14} />
          </button>
          {showUserMenu && (
            <UserMenu
              users={users}
              currentUser={currentUser}
              onSwitchUser={onSwitchUser}
              onCreateUser={onCreateUser}
            />
          )}
        </div>
      </div>
    </div>
  )
}
