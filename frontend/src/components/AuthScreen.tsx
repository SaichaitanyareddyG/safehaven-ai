import { Lock } from 'lucide-react'
import type { FormEventHandler, ReactNode } from 'react'

import { BrandPanel } from '@/components/BrandPanel'

/** Shared input look of the sign-in screens. */
export const authField =
  'h-[52px] w-full rounded-xl border-[1.5px] border-[#CBD4D3] bg-white px-4 text-base text-[#0B0D0E] outline-none ' +
  'placeholder:text-[#7A8588] focus-visible:border-[#0E7C72] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/30 ' +
  'aria-invalid:border-red-600'

export const authButton =
  'mt-1 h-[54px] rounded-xl bg-[#2EC4B6] text-[17px] font-semibold text-[#062320] transition-colors hover:bg-[#27B0A3] ' +
  'focus-visible:ring-3 focus-visible:ring-[#0E7C72]/50 focus-visible:outline-none disabled:opacity-60'

/**
 * The frame of every signed-out screen besides sign-in itself (choose a
 * password, forgot password): the brand panel and one big card.
 */
export function AuthScreen({ children, onSubmit }: { children: ReactNode; onSubmit?: FormEventHandler<HTMLFormElement> }) {
  return (
    <div className="flex min-h-screen flex-col bg-[#F4F7F6] lg:flex-row">
      <BrandPanel />
      <main className="relative -mt-10 flex flex-1 justify-center px-4 pb-8 lg:mt-0 lg:items-center lg:px-6 lg:py-12">
        <form
          className="flex w-full max-w-[480px] flex-col gap-5 self-start rounded-[20px] bg-white p-6 text-[#0B0D0E] shadow-[0_1px_2px_rgba(11,13,14,0.06),0_12px_40px_rgba(11,13,14,0.10)] sm:p-12 lg:self-center"
          onSubmit={onSubmit}
          noValidate
        >
          {children}
          <div className="flex items-center justify-center gap-2 border-t border-[#E3E9E8] pt-4 text-[13px] text-[#5B676A]">
            <Lock className="h-4 w-4" aria-hidden="true" />
            Authorised clinical staff · demo data only
          </div>
        </form>
      </main>
    </div>
  )
}
