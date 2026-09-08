INSERT INTO support_member_salaries
  (user_id, effective_from, annual_salary, currency, annual_working_hours, display_name, notes)
VALUES
  ('632db3dc140ba0bf651a3c6b', '2022-08-01', 34500.00, 'GBP', 2080, 'Lai-Ting Tang', 'Initial salary seed')
ON CONFLICT (user_id, effective_from) DO UPDATE
SET annual_salary=EXCLUDED.annual_salary,
    currency=EXCLUDED.currency,
    annual_working_hours=EXCLUDED.annual_working_hours,
    display_name=EXCLUDED.display_name,
    notes=EXCLUDED.notes;
