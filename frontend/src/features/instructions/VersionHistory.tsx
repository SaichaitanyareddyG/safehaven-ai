import { format } from 'date-fns'

import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FactsPanel } from '@/features/instructions/FactsPanel'
import { PatientOutputPanel } from '@/features/instructions/PatientOutputPanel'
import type { InstructionVersionRead } from '@/types/instructions'

export function VersionHistory({ versions }: { versions: InstructionVersionRead[] }) {
  if (versions.length <= 1) return null

  const sorted = [...versions].sort((a, b) => b.version_number - a.version_number)

  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold tracking-tight">Version history</h3>
      <Tabs defaultValue={String(sorted[0].version_number)}>
        <TabsList>
          {sorted.map((version) => (
            <TabsTrigger key={version.id} value={String(version.version_number)}>
              v{version.version_number}
              <Badge variant="secondary" className="ml-1.5">
                {version.source === 'ORIGINAL' ? 'Original' : 'Clarification'}
              </Badge>
            </TabsTrigger>
          ))}
        </TabsList>
        {sorted.map((version) => (
          <TabsContent key={version.id} value={String(version.version_number)} className="space-y-4">
            <div className="rounded-lg border bg-background p-4 text-sm">
              <p className="mb-1 text-xs text-muted-foreground">
                {format(new Date(version.created_at), 'PPp')}
              </p>
              {version.raw_text}
            </div>
            {version.extraction && <FactsPanel extraction={version.extraction} />}
            {version.patient_outputs.map((output) => (
              <PatientOutputPanel key={output.id} output={output} />
            ))}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
