import React from 'react'
import { Typography } from 'antd'

export default function MessageBubble({ role, content }: { role: 'user' | 'assistant'; content: string }) {
  const isUser = role === 'user'
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
      <div
        style={{
          maxWidth: '75%',
          background: isUser ? '#1677ff' : '#f5f5f5',
          color: isUser ? '#fff' : '#000',
          padding: '8px 12px',
          borderRadius: 12,
          borderTopRightRadius: isUser ? 2 : 12,
          borderTopLeftRadius: isUser ? 12 : 2,
          whiteSpace: 'pre-wrap',
          boxShadow: '0 1px 2px rgba(0,0,0,0.06)'
        }}
      >
        <Typography.Text style={{ color: isUser ? '#fff' : 'inherit', fontSize: 15, lineHeight: 1.7 }}>{content}</Typography.Text>
      </div>
    </div>
  )
}
