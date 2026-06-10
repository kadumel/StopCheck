from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import manager_required
from .forms import CompanyImportForm, DeliveryCompanyForm
from .models import DeliveryCompany, ImportBatch
from .services.import_service import process_import_batch


@manager_required
def import_list(request):
    org = request.user.profile.organization
    batches = ImportBatch.objects.filter(organization=org).select_related(
        'uploaded_by', 'delivery_company'
    )[:20]
    return render(request, 'stop_check/import/list.html', {'batches': batches})


@manager_required
def import_upload(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = CompanyImportForm(request.POST, request.FILES)
        form.fields['delivery_company'].queryset = DeliveryCompany.objects.filter(
            organization=org, is_active=True
        )
        if form.is_valid():
            batch = ImportBatch.objects.create(
                organization=org,
                uploaded_by=request.user,
                delivery_company=form.cleaned_data.get('delivery_company'),
                file=form.cleaned_data['file'],
            )
            process_import_batch(batch)
            if batch.status == ImportBatch.STATUS_COMPLETED:
                messages.success(
                    request,
                    f'Importação concluída: {batch.rows_updated} registo(s) atualizado(s).'
                )
            else:
                messages.warning(
                    request,
                    f'Importação com problemas: {batch.rows_failed} erro(s). Ver detalhes.'
                )
            return redirect('import_detail', pk=batch.pk)
    else:
        form = CompanyImportForm()
        form.fields['delivery_company'].queryset = DeliveryCompany.objects.filter(
            organization=org, is_active=True
        )
    return render(request, 'stop_check/import/upload.html', {'form': form})


@manager_required
def import_detail(request, pk):
    org = request.user.profile.organization
    batch = get_object_or_404(ImportBatch, pk=pk, organization=org)
    return render(request, 'stop_check/import/detail.html', {'batch': batch})


@manager_required
def delivery_company_list(request):
    org = request.user.profile.organization
    companies = DeliveryCompany.objects.filter(organization=org)
    return render(request, 'stop_check/import/companies.html', {'companies': companies})


@manager_required
def delivery_company_create(request):
    org = request.user.profile.organization
    if request.method == 'POST':
        form = DeliveryCompanyForm(request.POST)
        if form.is_valid():
            company = form.save(commit=False)
            company.organization = org
            company.save()
            messages.success(request, f'Empresa {company.name} adicionada.')
            return redirect('delivery_company_list')
    else:
        form = DeliveryCompanyForm()
    return render(request, 'stop_check/import/company_form.html', {
        'form': form, 'title': 'Nova Empresa de Entrega',
    })
