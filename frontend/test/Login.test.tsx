import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

import LoginPage from '@/app/login/page';

function respond(map: Record<string, () => Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    const key = Object.keys(map).find((k) => url.endsWith(k));
    if (!key) throw new Error(`unexpected request ${url}`);
    return map[key]();
  });
}

const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });

describe('Login', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it('shows the server error on wrong credentials', async () => {
    respond({ '/auth/setup-status': json({ has_users: true }), '/auth/login': json({ detail: 'Incorrect username or password.' }, 401) });
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText('Username'), 'guard');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect username or password.');
    expect(replace).not.toHaveBeenCalled();
  });

  it('explains how to create the first account', async () => {
    respond({ '/auth/setup-status': json({ has_users: false }) });
    render(<LoginPage />);
    expect(await screen.findByText(/No operator accounts exist yet/)).toBeInTheDocument();
  });

  it('redirects after signing in', async () => {
    respond({ '/auth/setup-status': json({ has_users: true }), '/auth/login': json({ id: 1, username: 'guard', role: 'operator' }) });
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText('Username'), 'guard');
    await userEvent.type(screen.getByLabelText('Password'), 'Secret12345');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/overview'));
  });
});
