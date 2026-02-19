import { useState } from 'react'
import { User, Plus } from 'lucide-react'

export default function UserMenu({ users, currentUser, onSwitchUser, onCreateUser }) {
  const [showForm, setShowForm] = useState(false)
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')

  const handleCreate = async () => {
    if (!newId.trim() || !newName.trim()) return
    try {
      await onCreateUser(newId.trim(), newName.trim())
      setNewId('')
      setNewName('')
      setShowForm(false)
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to create user')
    }
  }

  return (
    <div className="user-menu">
      {users.map(user => (
        <button
          key={user.user_id}
          className={`user-menu-item ${user.user_id === currentUser ? 'active' : ''}`}
          onClick={() => onSwitchUser(user.user_id)}
        >
          <User size={14} />
          <span>{user.display_name}</span>
        </button>
      ))}
      <div className="user-menu-divider" />
      {!showForm ? (
        <button className="user-menu-item add-user" onClick={() => setShowForm(true)}>
          <Plus size={14} />
          <span>New User</span>
        </button>
      ) : (
        <div className="new-user-form">
          <input
            type="text" placeholder="user-id" value={newId}
            onChange={e => setNewId(e.target.value)} className="new-user-input"
          />
          <input
            type="text" placeholder="Display Name" value={newName}
            onChange={e => setNewName(e.target.value)} className="new-user-input"
          />
          <div className="new-user-actions">
            <button className="btn-sm btn-primary" onClick={handleCreate}>Create</button>
            <button className="btn-sm btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
